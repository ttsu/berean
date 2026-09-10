// The client is thin, and what is worth asserting about it is exactly that:
// it carries the request across unchanged, returns what came back, and turns a
// transport failure into an error rather than into an answer. A real server on
// a loopback port rather than a mock, because a mock of gRPC would assert the
// mock.
package catena_test

import (
	"context"
	"errors"
	"net"
	"testing"

	"google.golang.org/grpc"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
	"github.com/ttsu/berean/services/gateway/internal/catena"
	"github.com/ttsu/berean/services/gateway/internal/turn"
)

type service struct {
	bereanv1.UnimplementedCatenaServiceServer
	seen *bereanv1.AnswerRequest
	fail error
}

func (s *service) Answer(_ context.Context, request *bereanv1.AnswerRequest) (*bereanv1.AnswerResponse, error) {
	s.seen = request
	if s.fail != nil {
		return nil, s.fail
	}
	return &bereanv1.AnswerResponse{
		Answer: &bereanv1.AnswerObject{NoAnswerReason: "Nothing in scope addresses it."},
		Trace:  &bereanv1.RetrievalTrace{RewrittenQuery: request.GetQuery()},
	}, nil
}

func serve(t *testing.T, impl *service) *catena.Client {
	t.Helper()
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	server := grpc.NewServer()
	bereanv1.RegisterCatenaServiceServer(server, impl)
	go func() { _ = server.Serve(listener) }()
	t.Cleanup(server.Stop)

	client, err := catena.Dial(listener.Addr().String())
	if err != nil {
		t.Fatalf("Dial: %v", err)
	}
	t.Cleanup(func() { _ = client.Close() })
	return client
}

func TestTheClientSatisfiesTheTurnsGenerator(t *testing.T) {
	// A compile-time assertion. The seam only holds if the one call the turn
	// knows how to make is the one this package makes.
	var _ turn.Generator = (*catena.Client)(nil)
}

func TestTheRequestCrossesUnchanged(t *testing.T) {
	impl := &service{}
	client := serve(t, impl)

	sent := &bereanv1.AnswerRequest{
		Query:     "When must the roll be read?",
		RequestId: "6f1a0b6e-9f3a-4a2e-9a8b-2d1f0c3b4a55",
		Attempt:   2,
		FilterSpec: &bereanv1.FilterSpec{TopK: 20, Corpora: []*bereanv1.CorpusFilter{
			{CorpusId: "alpha-1702-revised", Tier: bereanv1.Tier_TIER_BINDING},
		}},
		AnswerFailures: []*bereanv1.AnswerFailure{{
			Code:   bereanv1.AnswerFailureCode_ANSWER_FAILURE_CODE_CITATIONS_REQUIRED,
			Slot:   "arguments[0]",
			Detail: "an argument carries no citations",
		}},
	}
	response, err := client.Answer(context.Background(), sent)
	if err != nil {
		t.Fatalf("Answer: %v", err)
	}

	if impl.seen.GetAttempt() != 2 || impl.seen.GetQuery() != sent.GetQuery() {
		t.Errorf("server saw %v", impl.seen)
	}
	if len(impl.seen.GetAnswerFailures()) != 1 {
		t.Error("the answer-level failures did not cross the boundary")
	}
	if response.GetAnswer().GetNoAnswerReason() == "" {
		t.Error("the answer did not come back")
	}
}

func TestATransportFailureComesBackAsAnError(t *testing.T) {
	client := serve(t, &service{fail: status.Error(codes.Internal, "the generator refused the schema")})

	_, err := client.Answer(context.Background(), &bereanv1.AnswerRequest{Attempt: 1})

	if err == nil {
		t.Fatal("Answer returned no error")
	}
	if errors.Is(err, context.Canceled) {
		t.Errorf("err = %v, want the server's status", err)
	}
}
