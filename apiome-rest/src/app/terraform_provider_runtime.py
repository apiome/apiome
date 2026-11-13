"""The fixed half of the generated Terraform provider — SDK-4.4 (#4498).

:mod:`app.terraform_provider_generator` writes two kinds of Go: files that describe one contract
(the provider configuration, one spec table and schema per resource) and files that are the same
for every contract. This module holds the second kind, verbatim:

* :data:`RUNTIME_GO` — ``internal/provider/runtime.go``: the generic resource and the two generic
  data sources, plus the codec that moves values between Terraform's ``tftypes`` and decoded JSON.
  Every generated resource is this one implementation driven by a spec table, so a nested object, a
  list of objects and a map all travel through the same few functions.
* :data:`CLIENT_GO` — ``internal/client/client.go``: the JSON-over-HTTP transport.
* :data:`GO_MOD_REQUIRES` and :data:`GO_SUM` — the pinned dependency set. The provider imports the
  same Terraform Plugin Framework packages whatever the contract, so one ``go.sum`` serves every
  generated provider, and a consumer's ``go build`` needs no ``go mod tidy`` first.

Keeping them as text, rather than generating them, is what makes them reviewable: they were written
and compiled as ordinary Go, and ``tests/test_terraform_provider_generator.py`` builds, vets and
gofmt-checks them, with a generated provider around them, whenever a Go toolchain is on ``PATH``.

``__MODULE__`` in :data:`RUNTIME_GO` is replaced with the generated module path.
"""

# The Go sources and checksums below are embedded verbatim; their line lengths are Go's, not ours.
# ruff: noqa: E501

from __future__ import annotations

__all__ = [
    "CLIENT_GO",
    "GO_DIRECTIVE",
    "GO_MOD_REQUIRES",
    "GO_SUM",
    "MODULE_PLACEHOLDER",
    "PLUGIN_FRAMEWORK_VERSION",
    "PLUGIN_GO_VERSION",
    "RUNTIME_GO",
]

#: The token :data:`RUNTIME_GO` names the generated module by.
MODULE_PLACEHOLDER = "__MODULE__"

#: The ``go`` directive the generated ``go.mod`` declares — what the pinned framework requires.
GO_DIRECTIVE = "1.24.0"

#: The pinned Terraform Plugin Framework release.
PLUGIN_FRAMEWORK_VERSION = "v1.18.0"

#: The pinned terraform-plugin-go release (``tftypes``), matching the framework's own requirement.
PLUGIN_GO_VERSION = "v0.30.0"

#: The ``require`` block of indirect dependencies, as ``go mod tidy`` resolved it for the pins.
GO_MOD_REQUIRES = r'''require (
	github.com/fatih/color v1.18.0 // indirect
	github.com/golang/protobuf v1.5.4 // indirect
	github.com/hashicorp/go-hclog v1.6.3 // indirect
	github.com/hashicorp/go-plugin v1.7.0 // indirect
	github.com/hashicorp/go-uuid v1.0.3 // indirect
	github.com/hashicorp/terraform-plugin-log v0.10.0 // indirect
	github.com/hashicorp/terraform-registry-address v0.4.0 // indirect
	github.com/hashicorp/terraform-svchost v0.1.1 // indirect
	github.com/hashicorp/yamux v0.1.2 // indirect
	github.com/mattn/go-colorable v0.1.14 // indirect
	github.com/mattn/go-isatty v0.0.20 // indirect
	github.com/mitchellh/go-testing-interface v1.14.1 // indirect
	github.com/oklog/run v1.1.0 // indirect
	github.com/vmihailenco/msgpack/v5 v5.4.1 // indirect
	github.com/vmihailenco/tagparser/v2 v2.0.0 // indirect
	golang.org/x/net v0.48.0 // indirect
	golang.org/x/sys v0.39.0 // indirect
	golang.org/x/text v0.32.0 // indirect
	google.golang.org/genproto/googleapis/rpc v0.0.0-20251202230838-ff82c1b0f217 // indirect
	google.golang.org/grpc v1.79.1 // indirect
	google.golang.org/protobuf v1.36.11 // indirect
)
'''

#: The checksums of every module the pins resolve to.
GO_SUM = r'''github.com/bufbuild/protocompile v0.14.1 h1:iA73zAf/fyljNjQKwYzUHD6AD4R8KMasmwa/FBatYVw=
github.com/bufbuild/protocompile v0.14.1/go.mod h1:ppVdAIhbr2H8asPk6k4pY7t9zB1OU5DoEw9xY/FUi1c=
github.com/cespare/xxhash/v2 v2.3.0 h1:UL815xU9SqsFlibzuggzjXhog7bL6oX9BbNZnL2UFvs=
github.com/cespare/xxhash/v2 v2.3.0/go.mod h1:VGX0DQ3Q6kWi7AoAeZDth3/j3BFtOZR5XLFGgcrjCOs=
github.com/davecgh/go-spew v1.1.0/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/davecgh/go-spew v1.1.2-0.20180830191138-d8f796af33cc h1:U9qPSI2PIWSS1VwoXQT9A3Wy9MM3WgvqSxFWenqJduM=
github.com/davecgh/go-spew v1.1.2-0.20180830191138-d8f796af33cc/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/fatih/color v1.13.0/go.mod h1:kLAiJbzzSOZDVNGyDpeOxJ47H46qBXwg5ILebYFFOfk=
github.com/fatih/color v1.18.0 h1:S8gINlzdQ840/4pfAwic/ZE0djQEH3wM94VfqLTZcOM=
github.com/fatih/color v1.18.0/go.mod h1:4FelSpRwEGDpQ12mAdzqdOukCy4u8WUtOY6lkT/6HfU=
github.com/go-logr/logr v1.4.3 h1:CjnDlHq8ikf6E492q6eKboGOC0T8CDaOvkHCIg8idEI=
github.com/go-logr/logr v1.4.3/go.mod h1:9T104GzyrTigFIr8wt5mBrctHMim0Nb2HLGrmQ40KvY=
github.com/go-logr/stdr v1.2.2 h1:hSWxHoqTgW2S2qGc0LTAI563KZ5YKYRhT3MFKZMbjag=
github.com/go-logr/stdr v1.2.2/go.mod h1:mMo/vtBO5dYbehREoey6XUKy/eSumjCCveDpRre4VKE=
github.com/golang/protobuf v1.5.4 h1:i7eJL8qZTpSEXOPTxNKhASYpMn+8e5Q6AdndVa1dWek=
github.com/golang/protobuf v1.5.4/go.mod h1:lnTiLA8Wa4RWRcIUkrtSVa5nRhsEGBg48fD6rSs7xps=
github.com/google/go-cmp v0.7.0 h1:wk8382ETsv4JYUZwIsn6YpYiWiBsYLSJiTsyBybVuN8=
github.com/google/go-cmp v0.7.0/go.mod h1:pXiqmnSA92OHEEa9HXL2W4E7lf9JzCmGVUdgjX3N/iU=
github.com/google/uuid v1.6.0 h1:NIvaJDMOsjHA8n1jAhLSgzrAzy1Hgr+hNrb57e+94F0=
github.com/google/uuid v1.6.0/go.mod h1:TIyPZe4MgqvfeYDBFedMoGGpEw/LqOeaOT+nhxU+yHo=
github.com/hashicorp/go-hclog v1.6.3 h1:Qr2kF+eVWjTiYmU7Y31tYlP1h0q/X3Nl3tPGdaB11/k=
github.com/hashicorp/go-hclog v1.6.3/go.mod h1:W4Qnvbt70Wk/zYJryRzDRU/4r0kIg0PVHBcfoyhpF5M=
github.com/hashicorp/go-plugin v1.7.0 h1:YghfQH/0QmPNc/AZMTFE3ac8fipZyZECHdDPshfk+mA=
github.com/hashicorp/go-plugin v1.7.0/go.mod h1:BExt6KEaIYx804z8k4gRzRLEvxKVb+kn0NMcihqOqb8=
github.com/hashicorp/go-uuid v1.0.3 h1:2gKiV6YVmrJ1i2CKKa9obLvRieoRGviZFL26PcT/Co8=
github.com/hashicorp/go-uuid v1.0.3/go.mod h1:6SBZvOh/SIDV7/2o3Jml5SYk/TvGqwFJ/bN7x4byOro=
github.com/hashicorp/terraform-plugin-framework v1.18.0 h1:Xy6OfqSTZfAAKXSlJ810lYvuQvYkOpSUoNMQ9l2L1RA=
github.com/hashicorp/terraform-plugin-framework v1.18.0/go.mod h1:eeFIf68PME+kenJeqSrIcpHhYQK0TOyv7ocKdN4Z35E=
github.com/hashicorp/terraform-plugin-go v0.30.0 h1:VmEiD0n/ewxbvV5VI/bYwNtlSEAXtHaZlSnyUUuQK6k=
github.com/hashicorp/terraform-plugin-go v0.30.0/go.mod h1:8d523ORAW8OHgA9e8JKg0ezL3XUO84H0A25o4NY/jRo=
github.com/hashicorp/terraform-plugin-log v0.10.0 h1:eu2kW6/QBVdN4P3Ju2WiB2W3ObjkAsyfBsL3Wh1fj3g=
github.com/hashicorp/terraform-plugin-log v0.10.0/go.mod h1:/9RR5Cv2aAbrqcTSdNmY1NRHP4E3ekrXRGjqORpXyB0=
github.com/hashicorp/terraform-registry-address v0.4.0 h1:S1yCGomj30Sao4l5BMPjTGZmCNzuv7/GDTDX99E9gTk=
github.com/hashicorp/terraform-registry-address v0.4.0/go.mod h1:LRS1Ay0+mAiRkUyltGT+UHWkIqTFvigGn/LbMshfflE=
github.com/hashicorp/terraform-svchost v0.1.1 h1:EZZimZ1GxdqFRinZ1tpJwVxxt49xc/S52uzrw4x0jKQ=
github.com/hashicorp/terraform-svchost v0.1.1/go.mod h1:mNsjQfZyf/Jhz35v6/0LWcv26+X7JPS+buii2c9/ctc=
github.com/hashicorp/yamux v0.1.2 h1:XtB8kyFOyHXYVFnwT5C3+Bdo8gArse7j2AQ0DA0Uey8=
github.com/hashicorp/yamux v0.1.2/go.mod h1:C+zze2n6e/7wshOZep2A70/aQU6QBRWJO/G6FT1wIns=
github.com/jhump/protoreflect v1.17.0 h1:qOEr613fac2lOuTgWN4tPAtLL7fUSbuJL5X5XumQh94=
github.com/jhump/protoreflect v1.17.0/go.mod h1:h9+vUUL38jiBzck8ck+6G/aeMX8Z4QUY/NiJPwPNi+8=
github.com/mattn/go-colorable v0.1.9/go.mod h1:u6P/XSegPjTcexA+o6vUJrdnUu04hMope9wVRipJSqc=
github.com/mattn/go-colorable v0.1.12/go.mod h1:u5H1YNBxpqRaxsYJYSkiCWKzEfiAb1Gb520KVy5xxl4=
github.com/mattn/go-colorable v0.1.14 h1:9A9LHSqF/7dyVVX6g0U9cwm9pG3kP9gSzcuIPHPsaIE=
github.com/mattn/go-colorable v0.1.14/go.mod h1:6LmQG8QLFO4G5z1gPvYEzlUgJ2wF+stgPZH1UqBm1s8=
github.com/mattn/go-isatty v0.0.12/go.mod h1:cbi8OIDigv2wuxKPP5vlRcQ1OAZbq2CE4Kysco4FUpU=
github.com/mattn/go-isatty v0.0.14/go.mod h1:7GGIvUiUoEMVVmxf/4nioHXj79iQHKdU27kJ6hsGG94=
github.com/mattn/go-isatty v0.0.20 h1:xfD0iDuEKnDkl03q4limB+vH+GxLEtL/jb4xVJSWWEY=
github.com/mattn/go-isatty v0.0.20/go.mod h1:W+V8PltTTMOvKvAeJH7IuucS94S2C6jfK/D7dTCTo3Y=
github.com/mitchellh/go-testing-interface v1.14.1 h1:jrgshOhYAUVNMAJiKbEu7EqAwgJJ2JqpQmpLJOu07cU=
github.com/mitchellh/go-testing-interface v1.14.1/go.mod h1:gfgS7OtZj6MA4U1UrDRp04twqAjfvlZyCfX3sDjEym8=
github.com/oklog/run v1.1.0 h1:GEenZ1cK0+q0+wsJew9qUg/DyD8k3JzYsZAi5gYi2mA=
github.com/oklog/run v1.1.0/go.mod h1:sVPdnTZT1zYwAJeCMu2Th4T21pA3FPOQRfWjQlk7DVU=
github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
github.com/pmezard/go-difflib v1.0.1-0.20181226105442-5d4384ee4fb2 h1:Jamvg5psRIccs7FGNTlIRMkT8wgtp5eCXdBlqhYGL6U=
github.com/pmezard/go-difflib v1.0.1-0.20181226105442-5d4384ee4fb2/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
github.com/stretchr/objx v0.1.0/go.mod h1:HFkY916IF+rwdDfMAkV7OtwuqBVzrE8GR6GFx+wExME=
github.com/stretchr/testify v1.7.2/go.mod h1:R6va5+xMeoiuVRoj+gSkQ7d3FALtqAAGI1FQKckRals=
github.com/stretchr/testify v1.10.0 h1:Xv5erBjTwe/5IxqUQTdXv5kgmIvbHo3QQyRwhJsOfJA=
github.com/stretchr/testify v1.10.0/go.mod h1:r2ic/lqez/lEtzL7wO/rwa5dbSLXVDPFyf8C91i36aY=
github.com/vmihailenco/msgpack/v5 v5.4.1 h1:cQriyiUvjTwOHg8QZaPihLWeRAAVoCpE00IUPn0Bjt8=
github.com/vmihailenco/msgpack/v5 v5.4.1/go.mod h1:GaZTsDaehaPpQVyxrf5mtQlH+pc21PIudVV/E3rRQok=
github.com/vmihailenco/tagparser/v2 v2.0.0 h1:y09buUbR+b5aycVFQs/g70pqKVZNBmxwAhO7/IwNM9g=
github.com/vmihailenco/tagparser/v2 v2.0.0/go.mod h1:Wri+At7QHww0WTrCBeu4J6bNtoV6mEfg5OIWRZA9qds=
go.opentelemetry.io/auto/sdk v1.2.1 h1:jXsnJ4Lmnqd11kwkBV2LgLoFMZKizbCi5fNZ/ipaZ64=
go.opentelemetry.io/auto/sdk v1.2.1/go.mod h1:KRTj+aOaElaLi+wW1kO/DZRXwkF4C5xPbEe3ZiIhN7Y=
go.opentelemetry.io/otel v1.39.0 h1:8yPrr/S0ND9QEfTfdP9V+SiwT4E0G7Y5MO7p85nis48=
go.opentelemetry.io/otel v1.39.0/go.mod h1:kLlFTywNWrFyEdH0oj2xK0bFYZtHRYUdv1NklR/tgc8=
go.opentelemetry.io/otel/metric v1.39.0 h1:d1UzonvEZriVfpNKEVmHXbdf909uGTOQjA0HF0Ls5Q0=
go.opentelemetry.io/otel/metric v1.39.0/go.mod h1:jrZSWL33sD7bBxg1xjrqyDjnuzTUB0x1nBERXd7Ftcs=
go.opentelemetry.io/otel/sdk v1.39.0 h1:nMLYcjVsvdui1B/4FRkwjzoRVsMK8uL/cj0OyhKzt18=
go.opentelemetry.io/otel/sdk v1.39.0/go.mod h1:vDojkC4/jsTJsE+kh+LXYQlbL8CgrEcwmt1ENZszdJE=
go.opentelemetry.io/otel/sdk/metric v1.39.0 h1:cXMVVFVgsIf2YL6QkRF4Urbr/aMInf+2WKg+sEJTtB8=
go.opentelemetry.io/otel/sdk/metric v1.39.0/go.mod h1:xq9HEVH7qeX69/JnwEfp6fVq5wosJsY1mt4lLfYdVew=
go.opentelemetry.io/otel/trace v1.39.0 h1:2d2vfpEDmCJ5zVYz7ijaJdOF59xLomrvj7bjt6/qCJI=
go.opentelemetry.io/otel/trace v1.39.0/go.mod h1:88w4/PnZSazkGzz/w84VHpQafiU4EtqqlVdxWy+rNOA=
golang.org/x/net v0.48.0 h1:zyQRTTrjc33Lhh0fBgT/H3oZq9WuvRR5gPC70xpDiQU=
golang.org/x/net v0.48.0/go.mod h1:+ndRgGjkh8FGtu1w1FGbEC31if4VrNVMuKTgcAAnQRY=
golang.org/x/sys v0.0.0-20200116001909-b77594299b42/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
golang.org/x/sys v0.0.0-20200223170610-d5e6a3e2c0ae/go.mod h1:h1NjWce9XRLGQEsW7wpKNCjG9DtNlClVuFLEZdDNbEs=
golang.org/x/sys v0.0.0-20210630005230-0f9fa26af87c/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
golang.org/x/sys v0.0.0-20210927094055-39ccf1dd6fa6/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
golang.org/x/sys v0.0.0-20220503163025-988cb79eb6c6/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
golang.org/x/sys v0.6.0/go.mod h1:oPkhp1MJrh7nUepCBck5+mAzfO9JrbApNNgaTdGDITg=
golang.org/x/sys v0.39.0 h1:CvCKL8MeisomCi6qNZ+wbb0DN9E5AATixKsvNtMoMFk=
golang.org/x/sys v0.39.0/go.mod h1:OgkHotnGiDImocRcuBABYBEXf8A9a87e/uXjp9XT3ks=
golang.org/x/text v0.32.0 h1:ZD01bjUt1FQ9WJ0ClOL5vxgxOI/sVCNgX1YtKwcY0mU=
golang.org/x/text v0.32.0/go.mod h1:o/rUWzghvpD5TXrTIBuJU77MTaN0ljMWE47kxGJQ7jY=
gonum.org/v1/gonum v0.16.0 h1:5+ul4Swaf3ESvrOnidPp4GZbzf0mxVQpDCYUQE7OJfk=
gonum.org/v1/gonum v0.16.0/go.mod h1:fef3am4MQ93R2HHpKnLk4/Tbh/s0+wqD5nfa6Pnwy4E=
google.golang.org/genproto/googleapis/rpc v0.0.0-20251202230838-ff82c1b0f217 h1:gRkg/vSppuSQoDjxyiGfN4Upv/h/DQmIR10ZU8dh4Ww=
google.golang.org/genproto/googleapis/rpc v0.0.0-20251202230838-ff82c1b0f217/go.mod h1:7i2o+ce6H/6BluujYR+kqX3GKH+dChPTQU19wjRPiGk=
google.golang.org/grpc v1.79.1 h1:zGhSi45ODB9/p3VAawt9a+O/MULLl9dpizzNNpq7flY=
google.golang.org/grpc v1.79.1/go.mod h1:KmT0Kjez+0dde/v2j9vzwoAScgEPx/Bw1CYChhHLrHQ=
google.golang.org/protobuf v1.36.11 h1:fV6ZwhNocDyBLK0dj+fg8ektcVegBBuEolpbTQyBNVE=
google.golang.org/protobuf v1.36.11/go.mod h1:HTf+CrKn2C3g5S8VImy6tdcUvCska2kB7j23XfzDpco=
gopkg.in/check.v1 v0.0.0-20161208181325-20d25e280405/go.mod h1:Co6ibVJAznAaIkqp8huTwlJQCZ016jof/cbN4VW5Yz0=
gopkg.in/yaml.v3 v3.0.1 h1:fxVm/GzAzEWqLHuvctI91KS9hhNmmWOoWu0XTYJS7CA=
gopkg.in/yaml.v3 v3.0.1/go.mod h1:K4uyk7z7BCEPqu6E+C64Yfv1cQ7kz7rIZviUmN+EgEM=
'''

#: ``internal/client/client.go``.
CLIENT_GO = r'''// Package client is the HTTP transport the generated Terraform provider calls the API through.
//
// It speaks JSON and nothing else: a request body is any value encoding/json accepts, and a
// response body is decoded with UseNumber so an integer identifier survives the round trip
// exactly rather than passing through a float64.
package client

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
)

// maxErrorBody caps how much of an error response is quoted back to the practitioner.
const maxErrorBody = 4096

// Client sends requests to one API deployment.
type Client struct {
	// BaseURL is prefixed to every request path, without a trailing slash.
	BaseURL string
	// HTTP sends the requests. A nil value uses http.DefaultClient.
	HTTP *http.Client
	// UserAgent is sent on every request when non-empty.
	UserAgent string
	// Headers are added to every request (credentials, a mock session, a tenant header).
	Headers map[string]string
	// Query parameters are added to every request (an API key carried in the query string).
	Query map[string]string
	// Cookies are added to every request (an API key carried in a cookie).
	Cookies map[string]string
}

// APIError is a response whose status was not 2xx.
type APIError struct {
	// Method and Path identify the request that failed.
	Method string
	Path   string
	// Status is the HTTP status code the API answered with.
	Status int
	// Body is the start of the response body, for the diagnostic.
	Body string
}

// Error renders the failure the way a Terraform diagnostic shows it.
func (e *APIError) Error() string {
	message := fmt.Sprintf("%s %s returned HTTP %d", e.Method, e.Path, e.Status)
	if e.Body != "" {
		message += ": " + e.Body
	}
	return message
}

// IsNotFound reports whether err is an APIError carrying 404 or 410 — the answer that tells a
// resource it no longer exists remotely.
func IsNotFound(err error) bool {
	var apiErr *APIError
	if errors.As(err, &apiErr) {
		return apiErr.Status == http.StatusNotFound || apiErr.Status == http.StatusGone
	}
	return false
}

// Do sends one request and decodes the JSON response.
//
// path is appended to BaseURL verbatim, so callers escape path segments themselves. body is
// encoded as JSON when non-nil. The decoded response is nil when the API answered with no body.
func (c *Client) Do(ctx context.Context, method, path string, query url.Values, body any) (any, error) {
	target, err := url.Parse(strings.TrimRight(c.BaseURL, "/") + path)
	if err != nil {
		return nil, fmt.Errorf("building the request URL: %w", err)
	}
	values := target.Query()
	for key, value := range c.Query {
		values.Set(key, value)
	}
	for key, items := range query {
		for _, item := range items {
			values.Add(key, item)
		}
	}
	target.RawQuery = values.Encode()

	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			return nil, fmt.Errorf("encoding the request body: %w", err)
		}
		reader = bytes.NewReader(encoded)
	}
	req, err := http.NewRequestWithContext(ctx, method, target.String(), reader)
	if err != nil {
		return nil, fmt.Errorf("building the request: %w", err)
	}
	req.Header.Set("Accept", "application/json")
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	if c.UserAgent != "" {
		req.Header.Set("User-Agent", c.UserAgent)
	}
	for key, value := range c.Headers {
		req.Header.Set(key, value)
	}
	for name, value := range c.Cookies {
		req.AddCookie(&http.Cookie{Name: name, Value: value})
	}

	httpClient := c.HTTP
	if httpClient == nil {
		httpClient = http.DefaultClient
	}
	resp, err := httpClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("%s %s: %w", method, path, err)
	}
	defer resp.Body.Close()
	payload, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("%s %s: reading the response: %w", method, path, err)
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		text := strings.TrimSpace(string(payload))
		if len(text) > maxErrorBody {
			text = text[:maxErrorBody] + "…"
		}
		return nil, &APIError{Method: method, Path: path, Status: resp.StatusCode, Body: text}
	}
	if len(bytes.TrimSpace(payload)) == 0 {
		return nil, nil
	}
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.UseNumber()
	var out any
	if err := decoder.Decode(&out); err != nil {
		return nil, fmt.Errorf("%s %s: decoding the response: %w", method, path, err)
	}
	return out, nil
}
'''

#: ``internal/provider/runtime.go``. ``__MODULE__`` is the generated module path.
RUNTIME_GO = r'''package provider

// The generic half of the provider: one resource implementation and two data-source
// implementations, each driven by a spec table generated from the contract. Values move between
// Terraform and the API as tftypes values and decoded JSON, so a nested object, a list of
// objects and a map all travel through the same few functions rather than through one
// hand-written conversion per attribute.

import (
	"context"
	"encoding/json"
	"fmt"
	"math/big"
	"net/url"
	"regexp"
	"strconv"
	"strings"

	"github.com/hashicorp/terraform-plugin-framework/datasource"
	dschema "github.com/hashicorp/terraform-plugin-framework/datasource/schema"
	"github.com/hashicorp/terraform-plugin-framework/path"
	"github.com/hashicorp/terraform-plugin-framework/resource"
	rschema "github.com/hashicorp/terraform-plugin-framework/resource/schema"
	"github.com/hashicorp/terraform-plugin-framework/types"
	"github.com/hashicorp/terraform-plugin-go/tftypes"

	"__MODULE__/internal/client"
)

// valueKind is how one attribute's value is spelled on the JSON wire.
type valueKind int

const (
	kindString valueKind = iota
	kindInt
	kindFloat
	kindBool
	// kindJSON is a value the contract does not type precisely enough for a Terraform schema
	// (a union, an untyped object). Terraform holds it as a JSON-encoded string.
	kindJSON
	kindList
	kindMap
	kindObject
)

// field maps one Terraform attribute onto one JSON member.
type field struct {
	// attr is the Terraform attribute name.
	attr string
	// wire is the JSON member name.
	wire string
	// kind is the value's shape.
	kind valueKind
	// elem is the element of a list or the value of a map.
	elem *field
	// fields are the members of an object.
	fields []field
}

// attribute is one top-level attribute of a resource or data source.
type attribute struct {
	field
	// pathParam names the path template placeholder this attribute fills, when it fills one.
	// Such an attribute is never sent in a body and never read back from a response.
	pathParam string
	// create and update say whether the attribute is sent in that operation's request body.
	create bool
	update bool
}

// resourceSpec is everything the generic resource needs to know about one API resource.
type resourceSpec struct {
	// typeName is the resource type suffix after the provider name.
	typeName string
	// collectionPath is where a create is sent; itemPath addresses one instance.
	collectionPath string
	itemPath       string
	// idAttr is the attribute holding the instance identifier; idParam is its placeholder in
	// itemPath.
	idAttr  string
	idParam string
	// The HTTP methods of each operation. updateMethod is empty when the API has no update, in
	// which case every configurable attribute forces replacement.
	createMethod string
	readMethod   string
	updateMethod string
	deleteMethod string
	// attributes are the resource's top-level attributes, in schema order.
	attributes []attribute
	// importParts are the attributes an import ID names, slash-separated, in order. Empty when
	// import is disabled.
	importParts []string
}

// itemDataSourceSpec reads one instance by its identifier.
type itemDataSourceSpec struct {
	typeName   string
	itemPath   string
	attributes []attribute
}

// listDataSourceSpec reads every instance of a collection.
type listDataSourceSpec struct {
	typeName       string
	collectionPath string
	// listMember is the response member holding the array, or empty when the response body is
	// the array itself.
	listMember string
	// parents are the path-parameter attributes the collection is addressed by.
	parents []attribute
	// item describes one element of the computed "items" list.
	item field
}

// itemsAttribute is the attribute a list data source returns its elements under.
const itemsAttribute = "items"

// ---------------------------------------------------------------------------------------------
// Encoding: Terraform → JSON
// ---------------------------------------------------------------------------------------------

// encodeValue converts one Terraform value into the JSON value the API expects. include is
// false for a null or unknown value, which is left out of the request rather than sent as null.
func encodeValue(v tftypes.Value, f field) (out any, include bool, err error) {
	if !v.IsKnown() || v.IsNull() {
		return nil, false, nil
	}
	switch f.kind {
	case kindString:
		var s string
		err = v.As(&s)
		return s, err == nil, err
	case kindJSON:
		var s string
		if err = v.As(&s); err != nil {
			return nil, false, err
		}
		var decoded any
		if err = json.Unmarshal([]byte(s), &decoded); err != nil {
			return nil, false, fmt.Errorf("attribute %q must hold JSON: %w", f.attr, err)
		}
		return decoded, true, nil
	case kindInt, kindFloat:
		var n big.Float
		if err = v.As(&n); err != nil {
			return nil, false, err
		}
		if f.kind == kindInt {
			i, _ := n.Int64()
			return i, true, nil
		}
		x, _ := n.Float64()
		return x, true, nil
	case kindBool:
		var b bool
		err = v.As(&b)
		return b, err == nil, err
	case kindList:
		var items []tftypes.Value
		if err = v.As(&items); err != nil {
			return nil, false, err
		}
		list := make([]any, 0, len(items))
		for _, item := range items {
			encoded, _, err := encodeValue(item, *f.elem)
			if err != nil {
				return nil, false, err
			}
			list = append(list, encoded)
		}
		return list, true, nil
	case kindMap:
		var entries map[string]tftypes.Value
		if err = v.As(&entries); err != nil {
			return nil, false, err
		}
		object := make(map[string]any, len(entries))
		for key, item := range entries {
			encoded, _, err := encodeValue(item, *f.elem)
			if err != nil {
				return nil, false, err
			}
			object[key] = encoded
		}
		return object, true, nil
	case kindObject:
		var members map[string]tftypes.Value
		if err = v.As(&members); err != nil {
			return nil, false, err
		}
		object, err := encodeObject(members, f.fields)
		return object, err == nil, err
	}
	return nil, false, fmt.Errorf("attribute %q has an unsupported kind", f.attr)
}

// encodeObject converts an object's members into a JSON object, keyed by wire name.
func encodeObject(members map[string]tftypes.Value, fields []field) (map[string]any, error) {
	object := make(map[string]any, len(fields))
	for _, f := range fields {
		value, ok := members[f.attr]
		if !ok {
			continue
		}
		encoded, include, err := encodeValue(value, f)
		if err != nil {
			return nil, err
		}
		if include {
			object[f.wire] = encoded
		}
	}
	return object, nil
}

// ---------------------------------------------------------------------------------------------
// Decoding: JSON → Terraform
// ---------------------------------------------------------------------------------------------

// decodeValue converts one decoded JSON value into a Terraform value of type typ. An absent or
// null JSON value becomes a null Terraform value.
func decodeValue(raw any, f field, typ tftypes.Type) (tftypes.Value, error) {
	if raw == nil {
		return tftypes.NewValue(typ, nil), nil
	}
	mismatch := func() (tftypes.Value, error) {
		return tftypes.Value{}, fmt.Errorf("the API returned %T for attribute %q", raw, f.attr)
	}
	switch f.kind {
	case kindString:
		switch value := raw.(type) {
		case string:
			return tftypes.NewValue(typ, value), nil
		case json.Number:
			return tftypes.NewValue(typ, value.String()), nil
		case bool:
			return tftypes.NewValue(typ, strconv.FormatBool(value)), nil
		}
		return mismatch()
	case kindJSON:
		encoded, err := json.Marshal(raw)
		if err != nil {
			return tftypes.Value{}, err
		}
		return tftypes.NewValue(typ, string(encoded)), nil
	case kindInt, kindFloat:
		var text string
		switch value := raw.(type) {
		case json.Number:
			text = value.String()
		case string:
			text = value
		default:
			return mismatch()
		}
		n, ok := new(big.Float).SetString(text)
		if !ok {
			return mismatch()
		}
		return tftypes.NewValue(typ, n), nil
	case kindBool:
		value, ok := raw.(bool)
		if !ok {
			return mismatch()
		}
		return tftypes.NewValue(typ, value), nil
	case kindList:
		items, ok := raw.([]any)
		if !ok {
			return mismatch()
		}
		listType, ok := typ.(tftypes.List)
		if !ok {
			return mismatch()
		}
		values := make([]tftypes.Value, 0, len(items))
		for _, item := range items {
			decoded, err := decodeValue(item, *f.elem, listType.ElementType)
			if err != nil {
				return tftypes.Value{}, err
			}
			values = append(values, decoded)
		}
		return tftypes.NewValue(typ, values), nil
	case kindMap:
		entries, ok := raw.(map[string]any)
		if !ok {
			return mismatch()
		}
		mapType, ok := typ.(tftypes.Map)
		if !ok {
			return mismatch()
		}
		values := make(map[string]tftypes.Value, len(entries))
		for key, item := range entries {
			decoded, err := decodeValue(item, *f.elem, mapType.ElementType)
			if err != nil {
				return tftypes.Value{}, err
			}
			values[key] = decoded
		}
		return tftypes.NewValue(typ, values), nil
	case kindObject:
		members, ok := raw.(map[string]any)
		if !ok {
			return mismatch()
		}
		objectType, ok := typ.(tftypes.Object)
		if !ok {
			return mismatch()
		}
		return decodeObject(members, f.fields, objectType)
	}
	return mismatch()
}

// decodeObject converts a JSON object into a Terraform object of type typ. A member the
// response left out becomes null.
func decodeObject(members map[string]any, fields []field, typ tftypes.Object) (tftypes.Value, error) {
	values := make(map[string]tftypes.Value, len(typ.AttributeTypes))
	for _, f := range fields {
		decoded, err := decodeValue(members[f.wire], f, typ.AttributeTypes[f.attr])
		if err != nil {
			return tftypes.Value{}, err
		}
		values[f.attr] = decoded
	}
	for name, attrType := range typ.AttributeTypes {
		if _, ok := values[name]; !ok {
			values[name] = tftypes.NewValue(attrType, nil)
		}
	}
	return tftypes.NewValue(typ, values), nil
}

// ---------------------------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------------------------

// placeholder matches one {name} segment of a path template.
var placeholder = regexp.MustCompile(`\{([^{}]+)\}`)

// objectMembers splits a Terraform object value into its attribute values.
func objectMembers(v tftypes.Value) (map[string]tftypes.Value, tftypes.Object, error) {
	objectType, ok := v.Type().(tftypes.Object)
	if !ok {
		return nil, tftypes.Object{}, fmt.Errorf("expected an object, got %s", v.Type())
	}
	members := map[string]tftypes.Value{}
	if v.IsKnown() && !v.IsNull() {
		if err := v.As(&members); err != nil {
			return nil, tftypes.Object{}, err
		}
	}
	return members, objectType, nil
}

// scalarText renders a known string or number value as the text a path segment carries.
func scalarText(v tftypes.Value) (string, error) {
	if !v.IsKnown() || v.IsNull() {
		return "", fmt.Errorf("value is not known")
	}
	if v.Type().Is(tftypes.Number) {
		var n big.Float
		if err := v.As(&n); err != nil {
			return "", err
		}
		return n.Text('f', -1), nil
	}
	var s string
	if err := v.As(&s); err != nil {
		return "", err
	}
	return s, nil
}

// expandPath fills a path template's placeholders. values maps a placeholder name to the
// attribute value that fills it.
func expandPath(template string, values map[string]tftypes.Value) (string, error) {
	var failure error
	expanded := placeholder.ReplaceAllStringFunc(template, func(token string) string {
		name := token[1 : len(token)-1]
		value, ok := values[name]
		if !ok {
			failure = fmt.Errorf("no value for path parameter %q", name)
			return token
		}
		text, err := scalarText(value)
		if err != nil {
			failure = fmt.Errorf("path parameter %q: %w", name, err)
			return token
		}
		return url.PathEscape(text)
	})
	return expanded, failure
}

// pathValues collects the values that fill a path template's placeholders.
func pathValues(attributes []attribute, members map[string]tftypes.Value, idParam, idAttr string) map[string]tftypes.Value {
	values := map[string]tftypes.Value{}
	for _, a := range attributes {
		if a.pathParam != "" {
			values[a.pathParam] = members[a.attr]
		}
	}
	if idParam != "" {
		values[idParam] = members[idAttr]
	}
	return values
}

// requestBody encodes the attributes an operation sends.
func requestBody(attributes []attribute, members map[string]tftypes.Value, update bool) (map[string]any, error) {
	body := map[string]any{}
	for _, a := range attributes {
		if (update && !a.update) || (!update && !a.create) {
			continue
		}
		encoded, include, err := encodeValue(members[a.attr], a.field)
		if err != nil {
			return nil, err
		}
		if include {
			body[a.wire] = encoded
		}
	}
	return body, nil
}

// mergeState builds the state to store from what Terraform planned (or held) and what the API
// answered.
//
// After a create or update (refresh false), every part of a value the plan already knows is kept
// exactly — Terraform rejects a provider that stores something other than what it planned — and
// only the parts the plan left unknown are taken from the API. On a refresh (refresh true), every value
// the API returned replaces the stored one, so drift is detected, and a member the response left
// out keeps its stored value, so a write-only field does not read as removed.
func mergeState(prior map[string]tftypes.Value, typ tftypes.Object, attributes []attribute, answer map[string]any, refresh bool) (tftypes.Value, error) {
	values := make(map[string]tftypes.Value, len(typ.AttributeTypes))
	for _, a := range attributes {
		attrType := typ.AttributeTypes[a.attr]
		current, held := prior[a.attr]
		if !held {
			current = tftypes.NewValue(attrType, nil)
		}
		raw, answered := answer[a.wire]
		switch {
		case a.pathParam != "":
			values[a.attr] = current
		case !refresh:
			resolved, err := resolveUnknowns(current, raw, a.field)
			if err != nil {
				return tftypes.Value{}, err
			}
			values[a.attr] = resolved
		case refresh && !answered:
			values[a.attr] = current
		default:
			decoded, err := decodeValue(raw, a.field, attrType)
			if err != nil {
				return tftypes.Value{}, err
			}
			values[a.attr] = decoded
		}
	}
	for name, attrType := range typ.AttributeTypes {
		if _, ok := values[name]; !ok {
			values[name] = tftypes.NewValue(attrType, nil)
		}
	}
	return tftypes.NewValue(typ, values), nil
}

// resolveUnknowns fills the parts of a planned value Terraform left unknown from the API's
// answer, keeping every part the plan already knows. A nested object can be known while one of
// its computed members is not, so the walk recurses rather than stopping at the top.
func resolveUnknowns(planned tftypes.Value, raw any, f field) (tftypes.Value, error) {
	if planned.IsFullyKnown() {
		return planned, nil
	}
	if !planned.IsKnown() {
		return decodeValue(raw, f, planned.Type())
	}
	switch f.kind {
	case kindObject:
		var members map[string]tftypes.Value
		if err := planned.As(&members); err != nil {
			return tftypes.Value{}, err
		}
		answer, _ := raw.(map[string]any)
		for _, sub := range f.fields {
			member, ok := members[sub.attr]
			if !ok {
				continue
			}
			resolved, err := resolveUnknowns(member, answer[sub.wire], sub)
			if err != nil {
				return tftypes.Value{}, err
			}
			members[sub.attr] = resolved
		}
		return tftypes.NewValue(planned.Type(), members), nil
	case kindList:
		var items []tftypes.Value
		if err := planned.As(&items); err != nil {
			return tftypes.Value{}, err
		}
		answer, _ := raw.([]any)
		for index, item := range items {
			var element any
			if index < len(answer) {
				element = answer[index]
			}
			resolved, err := resolveUnknowns(item, element, *f.elem)
			if err != nil {
				return tftypes.Value{}, err
			}
			items[index] = resolved
		}
		return tftypes.NewValue(planned.Type(), items), nil
	case kindMap:
		var entries map[string]tftypes.Value
		if err := planned.As(&entries); err != nil {
			return tftypes.Value{}, err
		}
		answer, _ := raw.(map[string]any)
		for key, item := range entries {
			resolved, err := resolveUnknowns(item, answer[key], *f.elem)
			if err != nil {
				return tftypes.Value{}, err
			}
			entries[key] = resolved
		}
		return tftypes.NewValue(planned.Type(), entries), nil
	}
	return decodeValue(raw, f, planned.Type())
}

// asObject narrows a decoded response body to a JSON object.
func asObject(answer any, what string) (map[string]any, error) {
	object, ok := answer.(map[string]any)
	if !ok {
		return nil, fmt.Errorf("%s: the API did not return a JSON object", what)
	}
	return object, nil
}

// configuredClient narrows ProviderData to the API client the provider configured.
func configuredClient(data any) (*client.Client, error) {
	if data == nil {
		return nil, nil
	}
	c, ok := data.(*client.Client)
	if !ok {
		return nil, fmt.Errorf("unexpected provider data %T", data)
	}
	return c, nil
}

// ---------------------------------------------------------------------------------------------
// The resource
// ---------------------------------------------------------------------------------------------

// crudResource is a Terraform resource backed by a create/read/update/delete operation group.
type crudResource struct {
	spec   resourceSpec
	schema func() resourceSchema
	client *client.Client
}

// importableResource is a crudResource whose instances can be adopted with terraform import.
type importableResource struct {
	crudResource
}

var (
	_ resource.ResourceWithConfigure   = (*crudResource)(nil)
	_ resource.ResourceWithImportState = (*importableResource)(nil)
)

// newResource returns the resource implementation for spec, importable when spec allows it.
func newResource(spec resourceSpec, schema func() resourceSchema) resource.Resource {
	base := crudResource{spec: spec, schema: schema}
	if len(spec.importParts) > 0 {
		return &importableResource{crudResource: base}
	}
	return &base
}

// Metadata names the resource type.
func (r *crudResource) Metadata(_ context.Context, req resource.MetadataRequest, resp *resource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_" + r.spec.typeName
}

// Schema returns the generated schema.
func (r *crudResource) Schema(_ context.Context, _ resource.SchemaRequest, resp *resource.SchemaResponse) {
	resp.Schema = r.schema()
}

// Configure receives the API client from the provider.
func (r *crudResource) Configure(_ context.Context, req resource.ConfigureRequest, resp *resource.ConfigureResponse) {
	c, err := configuredClient(req.ProviderData)
	if err != nil {
		resp.Diagnostics.AddError("Unexpected provider data", err.Error())
		return
	}
	r.client = c
}

// fetch reads one instance. found is false when the API says it does not exist.
func (r *crudResource) fetch(ctx context.Context, members map[string]tftypes.Value) (answer map[string]any, found bool, err error) {
	target, err := expandPath(r.spec.itemPath, pathValues(r.spec.attributes, members, r.spec.idParam, r.spec.idAttr))
	if err != nil {
		return nil, false, err
	}
	raw, err := r.client.Do(ctx, r.spec.readMethod, target, nil, nil)
	if client.IsNotFound(err) {
		return nil, false, nil
	}
	if err != nil {
		return nil, false, err
	}
	answer, err = asObject(raw, "read")
	return answer, err == nil, err
}

// Create sends the create operation, then reads the instance back so every computed attribute
// is known.
func (r *crudResource) Create(ctx context.Context, req resource.CreateRequest, resp *resource.CreateResponse) {
	members, typ, err := objectMembers(req.Plan.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the plan", err.Error())
		return
	}
	body, err := requestBody(r.spec.attributes, members, false)
	if err != nil {
		resp.Diagnostics.AddError("Encoding the request", err.Error())
		return
	}
	target, err := expandPath(r.spec.collectionPath, pathValues(r.spec.attributes, members, "", ""))
	if err != nil {
		resp.Diagnostics.AddError("Building the request path", err.Error())
		return
	}
	raw, err := r.client.Do(ctx, r.spec.createMethod, target, nil, body)
	if err != nil {
		resp.Diagnostics.AddError("Creating "+r.spec.typeName, err.Error())
		return
	}
	created, err := asObject(raw, "create")
	if err != nil {
		resp.Diagnostics.AddError("Creating "+r.spec.typeName, err.Error())
		return
	}
	identity, err := r.identity(created, members, typ)
	if err != nil {
		resp.Diagnostics.AddError("Creating "+r.spec.typeName, err.Error())
		return
	}
	members[r.spec.idAttr] = identity
	answer, found, err := r.fetch(ctx, members)
	if err != nil || !found {
		// The create succeeded; what it answered is the best description of the instance.
		answer = created
	}
	state, err := mergeState(members, typ, r.spec.attributes, answer, false)
	if err != nil {
		resp.Diagnostics.AddError("Storing the new state", err.Error())
		return
	}
	resp.State.Raw = state
}

// identity reads the new instance's identifier out of the create response.
func (r *crudResource) identity(created map[string]any, members map[string]tftypes.Value, typ tftypes.Object) (tftypes.Value, error) {
	for _, a := range r.spec.attributes {
		if a.attr != r.spec.idAttr {
			continue
		}
		if planned := members[a.attr]; planned.IsKnown() && !planned.IsNull() {
			return planned, nil
		}
		raw, ok := created[a.wire]
		if !ok || raw == nil {
			return tftypes.Value{}, fmt.Errorf("the create response did not carry %q", a.wire)
		}
		return decodeValue(raw, a.field, typ.AttributeTypes[a.attr])
	}
	return tftypes.Value{}, fmt.Errorf("no identifier attribute %q", r.spec.idAttr)
}

// Read refreshes the stored state, and drops the resource when the API no longer has it.
func (r *crudResource) Read(ctx context.Context, req resource.ReadRequest, resp *resource.ReadResponse) {
	members, typ, err := objectMembers(req.State.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the state", err.Error())
		return
	}
	answer, found, err := r.fetch(ctx, members)
	if err != nil {
		resp.Diagnostics.AddError("Reading "+r.spec.typeName, err.Error())
		return
	}
	if !found {
		resp.State.RemoveResource(ctx)
		return
	}
	state, err := mergeState(members, typ, r.spec.attributes, answer, true)
	if err != nil {
		resp.Diagnostics.AddError("Storing the refreshed state", err.Error())
		return
	}
	resp.State.Raw = state
}

// Update sends the update operation, then reads the instance back.
func (r *crudResource) Update(ctx context.Context, req resource.UpdateRequest, resp *resource.UpdateResponse) {
	if r.spec.updateMethod == "" {
		resp.Diagnostics.AddError("Update not supported", "The API has no update operation for "+r.spec.typeName+"; every change replaces it.")
		return
	}
	members, typ, err := objectMembers(req.Plan.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the plan", err.Error())
		return
	}
	body, err := requestBody(r.spec.attributes, members, true)
	if err != nil {
		resp.Diagnostics.AddError("Encoding the request", err.Error())
		return
	}
	target, err := expandPath(r.spec.itemPath, pathValues(r.spec.attributes, members, r.spec.idParam, r.spec.idAttr))
	if err != nil {
		resp.Diagnostics.AddError("Building the request path", err.Error())
		return
	}
	raw, err := r.client.Do(ctx, r.spec.updateMethod, target, nil, body)
	if err != nil {
		resp.Diagnostics.AddError("Updating "+r.spec.typeName, err.Error())
		return
	}
	answer, found, err := r.fetch(ctx, members)
	if err != nil || !found {
		answer, _ = raw.(map[string]any)
	}
	state, err := mergeState(members, typ, r.spec.attributes, answer, false)
	if err != nil {
		resp.Diagnostics.AddError("Storing the new state", err.Error())
		return
	}
	resp.State.Raw = state
}

// Delete sends the delete operation. An instance that is already gone counts as deleted.
func (r *crudResource) Delete(ctx context.Context, req resource.DeleteRequest, resp *resource.DeleteResponse) {
	members, _, err := objectMembers(req.State.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the state", err.Error())
		return
	}
	target, err := expandPath(r.spec.itemPath, pathValues(r.spec.attributes, members, r.spec.idParam, r.spec.idAttr))
	if err != nil {
		resp.Diagnostics.AddError("Building the request path", err.Error())
		return
	}
	if _, err := r.client.Do(ctx, r.spec.deleteMethod, target, nil, nil); err != nil && !client.IsNotFound(err) {
		resp.Diagnostics.AddError("Deleting "+r.spec.typeName, err.Error())
	}
}

// ImportState adopts an existing instance from an import ID naming spec.importParts,
// slash-separated.
func (r *importableResource) ImportState(ctx context.Context, req resource.ImportStateRequest, resp *resource.ImportStateResponse) {
	parts := strings.Split(req.ID, "/")
	if len(parts) != len(r.spec.importParts) {
		resp.Diagnostics.AddError(
			"Unexpected import ID",
			fmt.Sprintf("Expected %d slash-separated parts (%s), got %q.", len(r.spec.importParts), strings.Join(r.spec.importParts, "/"), req.ID),
		)
		return
	}
	for index, name := range r.spec.importParts {
		for _, a := range r.spec.attributes {
			if a.attr != name {
				continue
			}
			if a.kind == kindInt {
				number, err := strconv.ParseInt(parts[index], 10, 64)
				if err != nil {
					resp.Diagnostics.AddError("Unexpected import ID", fmt.Sprintf("%s must be an integer, got %q.", name, parts[index]))
					return
				}
				resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root(name), types.Int64Value(number))...)
			} else {
				resp.Diagnostics.Append(resp.State.SetAttribute(ctx, path.Root(name), types.StringValue(parts[index]))...)
			}
		}
	}
}

// ---------------------------------------------------------------------------------------------
// The data sources
// ---------------------------------------------------------------------------------------------

// itemDataSource reads one instance by the attributes that address it.
type itemDataSource struct {
	spec   itemDataSourceSpec
	schema func() dataSourceSchema
	client *client.Client
}

var _ datasource.DataSourceWithConfigure = (*itemDataSource)(nil)

// Metadata names the data source.
func (d *itemDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_" + d.spec.typeName
}

// Schema returns the generated schema.
func (d *itemDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = d.schema()
}

// Configure receives the API client from the provider.
func (d *itemDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	c, err := configuredClient(req.ProviderData)
	if err != nil {
		resp.Diagnostics.AddError("Unexpected provider data", err.Error())
		return
	}
	d.client = c
}

// Read fetches the instance.
func (d *itemDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	members, typ, err := objectMembers(req.Config.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the configuration", err.Error())
		return
	}
	target, err := expandPath(d.spec.itemPath, pathValues(d.spec.attributes, members, "", ""))
	if err != nil {
		resp.Diagnostics.AddError("Building the request path", err.Error())
		return
	}
	raw, err := d.client.Do(ctx, methodGet, target, nil, nil)
	if err != nil {
		resp.Diagnostics.AddError("Reading "+d.spec.typeName, err.Error())
		return
	}
	answer, err := asObject(raw, "read")
	if err != nil {
		resp.Diagnostics.AddError("Reading "+d.spec.typeName, err.Error())
		return
	}
	state, err := mergeState(members, typ, d.spec.attributes, answer, true)
	if err != nil {
		resp.Diagnostics.AddError("Storing the result", err.Error())
		return
	}
	resp.State.Raw = state
}

// listDataSource reads every instance of a collection.
type listDataSource struct {
	spec   listDataSourceSpec
	schema func() dataSourceSchema
	client *client.Client
}

var _ datasource.DataSourceWithConfigure = (*listDataSource)(nil)

// Metadata names the data source.
func (d *listDataSource) Metadata(_ context.Context, req datasource.MetadataRequest, resp *datasource.MetadataResponse) {
	resp.TypeName = req.ProviderTypeName + "_" + d.spec.typeName
}

// Schema returns the generated schema.
func (d *listDataSource) Schema(_ context.Context, _ datasource.SchemaRequest, resp *datasource.SchemaResponse) {
	resp.Schema = d.schema()
}

// Configure receives the API client from the provider.
func (d *listDataSource) Configure(_ context.Context, req datasource.ConfigureRequest, resp *datasource.ConfigureResponse) {
	c, err := configuredClient(req.ProviderData)
	if err != nil {
		resp.Diagnostics.AddError("Unexpected provider data", err.Error())
		return
	}
	d.client = c
}

// Read fetches the collection.
func (d *listDataSource) Read(ctx context.Context, req datasource.ReadRequest, resp *datasource.ReadResponse) {
	members, typ, err := objectMembers(req.Config.Raw)
	if err != nil {
		resp.Diagnostics.AddError("Reading the configuration", err.Error())
		return
	}
	target, err := expandPath(d.spec.collectionPath, pathValues(d.spec.parents, members, "", ""))
	if err != nil {
		resp.Diagnostics.AddError("Building the request path", err.Error())
		return
	}
	raw, err := d.client.Do(ctx, methodGet, target, nil, nil)
	if err != nil {
		resp.Diagnostics.AddError("Reading "+d.spec.typeName, err.Error())
		return
	}
	if d.spec.listMember != "" {
		object, err := asObject(raw, "list")
		if err != nil {
			resp.Diagnostics.AddError("Reading "+d.spec.typeName, err.Error())
			return
		}
		raw = object[d.spec.listMember]
	}
	if raw == nil {
		raw = []any{}
	}
	itemsField := field{attr: itemsAttribute, wire: itemsAttribute, kind: kindList, elem: &d.spec.item}
	items, err := decodeValue(raw, itemsField, typ.AttributeTypes[itemsAttribute])
	if err != nil {
		resp.Diagnostics.AddError("Reading "+d.spec.typeName, err.Error())
		return
	}
	values := map[string]tftypes.Value{itemsAttribute: items}
	for _, parent := range d.spec.parents {
		values[parent.attr] = members[parent.attr]
	}
	resp.State.Raw = tftypes.NewValue(typ, values)
}

// methodGet is the method both data sources read with.
const methodGet = "GET"

// resourceSchema and dataSourceSchema are the two schema types the generated files return.
type (
	resourceSchema   = rschema.Schema
	dataSourceSchema = dschema.Schema
)
'''
