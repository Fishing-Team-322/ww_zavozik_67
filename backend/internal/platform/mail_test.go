package platform

import (
	"context"
	"net"
	"net/textproto"
	"strings"
	"testing"
	"time"
)

func TestSMTPResetDeliveryAndTLSRequirement(t *testing.T) {
	for _, plaintext := range []bool{true, false} {
		t.Run(map[bool]string{true: "local_delivery", false: "require_tls"}[plaintext], func(t *testing.T) {
			listener, err := net.Listen("tcp", "127.0.0.1:0")
			if err != nil {
				t.Fatal(err)
			}
			defer listener.Close()
			messages := make(chan string, 1)
			go func() {
				conn, err := listener.Accept()
				if err != nil {
					messages <- ""
					return
				}
				defer conn.Close()
				conn.SetDeadline(time.Now().Add(5 * time.Second))
				c := textproto.NewConn(conn)
				c.PrintfLine("220 localhost ESMTP")
				for {
					line, err := c.ReadLine()
					if err != nil {
						messages <- ""
						return
					}
					switch {
					case strings.HasPrefix(line, "EHLO"):
						c.PrintfLine("250 localhost")
					case strings.HasPrefix(line, "MAIL FROM:") || strings.HasPrefix(line, "RCPT TO:"):
						c.PrintfLine("250 OK")
					case line == "DATA":
						c.PrintfLine("354 Send body")
						data, err := c.ReadDotBytes()
						if err != nil {
							messages <- ""
							return
						}
						messages <- string(data)
						c.PrintfLine("250 queued")
					case line == "QUIT":
						c.PrintfLine("221 bye")
						return
					default:
						c.PrintfLine("500 unsupported")
					}
				}
			}()
			sender := SMTPMailer{Addr: listener.Addr().String(), From: "noreply@example.com", LocalPlaintext: plaintext}
			err = sender.SendReset(context.Background(), "owner@example.com", "http://localhost:3000/reset-password#token=one-time-secret")
			if plaintext {
				if err != nil {
					t.Fatal(err)
				}
				body := <-messages
				if !strings.Contains(body, "#token=one-time-secret") || !strings.Contains(body, "To: owner@example.com") {
					t.Fatal("mail body", body)
				}
			} else {
				if err == nil {
					t.Fatal("accepted missing STARTTLS")
				}
				<-messages
			}
		})
	}
}
