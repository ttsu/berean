// Package catena is the gateway's client for the one call.
//
// It is deliberately thin. Everything about *when* to call, *how many times*,
// and *what to do with the answer* lives in `internal/turn`; this package
// dials, sends, and hands back what came. A retry policy here would be a
// second regeneration nobody counted (ADR-0010).
package catena

import (
	"context"
	"fmt"

	"google.golang.org/grpc"
	"google.golang.org/grpc/credentials/insecure"

	bereanv1 "github.com/ttsu/berean/gen/berean/v1"
)

// Client is a connection to Catena.
type Client struct {
	conn    *grpc.ClientConn
	service bereanv1.CatenaServiceClient
}

// Dial prepares a connection. It does not block on one: gRPC connects lazily
// and the first call reports what a dial-time probe would have, at the point a
// caller can do something about it.
//
// Insecure credentials, because the only deployment in Phase 1 is the compose
// network, where Catena is not published and the gateway reaches it by service
// name. A deployment that puts the two on different hosts needs transport
// credentials, and that is a change to this constructor rather than a
// configuration flag it should already have.
func Dial(address string) (*Client, error) {
	conn, err := grpc.NewClient(address, grpc.WithTransportCredentials(insecure.NewCredentials()))
	if err != nil {
		return nil, fmt.Errorf("catena at %s: %w", address, err)
	}
	return &Client{conn: conn, service: bereanv1.NewCatenaServiceClient(conn)}, nil
}

// Close releases the connection.
func (c *Client) Close() error { return c.conn.Close() }

// Answer makes one generation attempt.
func (c *Client) Answer(ctx context.Context, request *bereanv1.AnswerRequest) (*bereanv1.AnswerResponse, error) {
	response, err := c.service.Answer(ctx, request)
	if err != nil {
		return nil, fmt.Errorf("catena Answer: %w", err)
	}
	return response, nil
}
