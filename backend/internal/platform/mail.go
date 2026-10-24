package platform

import (
	"context"
	"crypto/tls"
	"fmt"
	"net"
	"net/mail"
	"net/smtp"
	"strings"
	"time"
)

type SMTPMailer struct {
	Addr, Username, Password, From string
	LocalPlaintext                 bool
}

func (m SMTPMailer) SendReset(ctx context.Context, to, link string) error {
	from, err := mail.ParseAddress(m.From)
	if err != nil {
		return fmt.Errorf("invalid SMTP_FROM")
	}
	recipient, err := mail.ParseAddress(to)
	if err != nil {
		return fmt.Errorf("invalid recipient")
	}
	host, _, err := net.SplitHostPort(m.Addr)
	if err != nil {
		return fmt.Errorf("invalid SMTP_ADDR")
	}
	dialer := net.Dialer{Timeout: 5 * time.Second}
	conn, err := dialer.DialContext(ctx, "tcp", m.Addr)
	if err != nil {
		return fmt.Errorf("mail connection failed")
	}
	defer conn.Close()
	deadline := time.Now().Add(10 * time.Second)
	if d, ok := ctx.Deadline(); ok && d.Before(deadline) {
		deadline = d
	}
	_ = conn.SetDeadline(deadline)
	client, err := smtp.NewClient(conn, host)
	if err != nil {
		return fmt.Errorf("mail greeting failed")
	}
	defer client.Close()
	if ok, _ := client.Extension("STARTTLS"); ok {
		if err = client.StartTLS(&tls.Config{ServerName: host, MinVersion: tls.VersionTLS12}); err != nil {
			return fmt.Errorf("mail TLS failed")
		}
	} else if !m.LocalPlaintext {
		return fmt.Errorf("mail TLS required")
	}
	if m.Username != "" {
		if err = client.Auth(smtp.PlainAuth("", m.Username, m.Password, host)); err != nil {
			return fmt.Errorf("mail authentication failed")
		}
	}
	if err = client.Mail(from.Address); err != nil {
		return fmt.Errorf("mail sender rejected")
	}
	if err = client.Rcpt(recipient.Address); err != nil {
		return fmt.Errorf("mail recipient rejected")
	}
	body := "From: " + from.Address + "\r\nTo: " + recipient.Address + "\r\nSubject: Zavozik password reset\r\nMIME-Version: 1.0\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\nДля смены пароля откройте ссылку (действует 30 минут):\r\n" + link + "\r\nЕсли вы не запрашивали смену пароля, проигнорируйте письмо.\r\n"
	if strings.ContainsAny(link, "\r\n") {
		return fmt.Errorf("invalid reset URL")
	}
	w, err := client.Data()
	if err != nil {
		return fmt.Errorf("mail data rejected")
	}
	if _, err = w.Write([]byte(body)); err != nil {
		return fmt.Errorf("mail write failed")
	}
	if err = w.Close(); err != nil {
		return fmt.Errorf("mail delivery failed")
	}
	return client.Quit()
}
