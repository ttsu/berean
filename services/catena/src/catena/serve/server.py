"""The gRPC server: what it loads, when it admits to being ready, and the lock.

Three things here are not boilerplate.

**Readiness is not liveness.** BGE-M3 is 2.3 GB and takes tens of seconds to
load from `/models`. The port is open long before it can answer, so the standard
gRPC health service reports NOT_SERVING until the encoder is in memory, and
compose waits on that rather than on a TCP connect. The gateway `depends_on`
catena, so the alternative is a first request that fails for a reason that reads
as a bug in the gateway.

**The encoder is serialised.** `SentenceTransformer.encode` makes no thread
safety promise, and the server is a thread pool. One embedding per request
against a generation measured in tens of seconds means the lock costs nothing
worth measuring, and the failure it prevents is the kind that reproduces once a
week.

**Weights are loaded once, at startup, not per request.** Ingestion pays that
cost per invocation because it is a batch job; the request path cannot.
"""

from __future__ import annotations

import os
import signal
import threading
from concurrent import futures
from typing import Sequence

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from berean.v1 import catena_pb2_grpc
from catena.serve import ServeError, generate, observability, postgres
from catena.serve.service import CatenaService

PORT_ENV = "CATENA_PORT"
DEFAULT_PORT = 50051

#: The name compose probes and the gateway would check. The service's own
#: fully-qualified name, so a second service in this process would carry its own
#: status rather than sharing one.
SERVICE_NAME = "berean.v1.CatenaService"

#: One embedding and one generation per request, and the generation dominates by
#: two orders of magnitude. Phase 1's client is a CLI; this is not a throughput
#: knob, it is enough concurrency that a health probe is answered while a
#: generation is in flight.
MAX_WORKERS = 4


class SerialisedEmbedder:
    """The encoder, one caller at a time.

    Delegates rather than subclasses so it fits any `Embedder`, which is what
    ADR-0006 asks the interface for.
    """

    def __init__(self, embedder) -> None:
        self._embedder = embedder
        self._lock = threading.Lock()
        self.name = embedder.name
        self.dim = embedder.dim
        self.max_tokens = embedder.max_tokens

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        with self._lock:
            return self._embedder.embed(texts)

    def count_tokens(self, texts: Sequence[str]) -> list[int]:
        with self._lock:
            return self._embedder.count_tokens(texts)


def build(port: int | None = None) -> tuple[grpc.Server, health.HealthServicer]:
    """Wire the server. The encoder is not loaded here — `serve` does that."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=MAX_WORKERS))
    health_servicer = health.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.NOT_SERVING)
    server.add_insecure_port(f"[::]:{port or _port()}")
    return server, health_servicer


def serve(port: int | None = None) -> int:
    """Load, announce, and block until terminated."""
    from catena.ingest import IngestionError, bge

    server, health_servicer = build(port)

    try:
        embedder = SerialisedEmbedder(bge.load())
    except IngestionError as error:
        # The weights are mounted, never baked in or fetched at run time
        # (ADR-0014, SHARED §1), so this is a provisioning failure and it must
        # be legible as one rather than as a startup crash.
        raise ServeError(str(error)) from error

    traces = observability.connect()
    service = CatenaService(
        embedder=embedder,
        generator=generate.connect(),
        store_factory=postgres.reader,
        observability=traces,
    )
    catena_pb2_grpc.add_CatenaServiceServicer_to_server(service, server)

    server.start()
    health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.SERVING)
    print(f"catena: serving on :{port or _port()} "
          f"({embedder.name}, dim {embedder.dim}; langfuse "
          f"{'on' if traces.enabled else 'off'})", flush=True)

    stopping = threading.Event()

    def _stop(*_):
        # NOT_SERVING first, so a probe in flight during a rolling restart is
        # told the truth rather than being refused a connection.
        health_servicer.set(SERVICE_NAME, health_pb2.HealthCheckResponse.NOT_SERVING)
        stopping.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    stopping.wait()
    server.stop(grace=10).wait()
    traces.flush()
    return 0


def probe(port: int | None = None, timeout: float = 5.0) -> int:
    """Exit 0 when the service reports SERVING. What the compose healthcheck runs."""
    channel = grpc.insecure_channel(f"localhost:{port or _port()}")
    try:
        response = health_pb2_grpc.HealthStub(channel).Check(
            health_pb2.HealthCheckRequest(service=SERVICE_NAME), timeout=timeout
        )
    except grpc.RpcError as error:
        print(f"catena: not serving ({error.code().name})", flush=True)
        return 1
    finally:
        channel.close()

    if response.status != health_pb2.HealthCheckResponse.SERVING:
        print(f"catena: not serving ({health_pb2.HealthCheckResponse.ServingStatus.Name(response.status)})",
              flush=True)
        return 1
    return 0


def _port() -> int:
    return int(os.environ.get(PORT_ENV) or DEFAULT_PORT)
