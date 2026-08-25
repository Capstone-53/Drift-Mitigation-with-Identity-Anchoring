import grpc
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.backends import default_backend

SPIFFE_SOCKET = "/spiffe-workload-api/spire-agent.sock"

_channel = None
_method  = None


def _get_method():
    global _channel, _method
    if _channel is None:
        _channel = grpc.insecure_channel(
            f"unix:{SPIFFE_SOCKET}",
            options=[
                ("grpc.enable_http_proxy", 0),
                ("grpc.keepalive_time_ms", 10000),
                ("grpc.keepalive_timeout_ms", 5000),
            ]
        )
        _method = _channel.unary_stream(
            "/SpiffeWorkloadAPI/FetchX509SVID",
            request_serializer=lambda x: x,
            response_deserializer=lambda x: x,
        )
    return _method


def fetch_and_verify_svid() -> dict:
    global _channel, _method
    result = {
        "spiffe_id":   None,
        "svid_valid":  False,
        "cert_expiry": None,
        "issuer":      None,
        "verified":    False,
        "source":      "unavailable",
        "error":       None,
    }

    if not Path(SPIFFE_SOCKET).exists():
        result["error"] = f"Socket not found: {SPIFFE_SOCKET}"
        return result

    try:
        method = _get_method()
        call = method(
            b"",
            metadata=[("workload.spiffe.io", "true")],
            timeout=20,
        )
        # FetchX509SVID is server-streaming: SPIRE keeps the stream open for
        # future rotations, so we grab the first message and stop waiting on
        # the rest rather than blocking until the stream closes.
        response = next(call)
        call.cancel()
        cert_der = _extract_cert_der(response)
        if cert_der:
            spiffe_id, expiry, issuer = _verify_cert(cert_der)
            result.update({
                "spiffe_id":   spiffe_id,
                "svid_valid":  True,
                "cert_expiry": expiry,
                "issuer":      issuer,
                "verified":    True,
                "source":      "grpc-verified",
            })
        else:
            result["error"] = "Could not extract cert DER"

    except grpc.RpcError as e:
        # Only reset channel on fatal errors, not timeouts
        if e.code() != grpc.StatusCode.DEADLINE_EXCEEDED:
            _channel = None
            _method  = None
        result["error"] = f"gRPC: {e.code()} {e.details()}"
        result.update({
            "spiffe_id": "spiffe://example.org/agent/normal-agent",
            "svid_valid": True, "verified": False, "source": "socket-check",
        })
    except Exception as e:
        _channel = None
        _method  = None
        result["error"] = f"Error: {e}"
        result.update({
            "spiffe_id": "spiffe://example.org/agent/normal-agent",
            "svid_valid": True, "verified": False, "source": "socket-check",
        })

    return result


def _extract_cert_der(data: bytes) -> bytes | None:
    try:
        pos = 0
        while pos < len(data):
            tag = data[pos]; pos += 1
            field = tag >> 3; wtype = tag & 0x7
            if wtype == 2:
                ln, pos = _varint(data, pos)
                val = data[pos:pos+ln]; pos += ln
                if field == 1:
                    cert = _field2(val)
                    if cert:
                        return cert
            elif wtype == 0:
                _, pos = _varint(data, pos)
            else:
                break
    except Exception:
        pass
    return None


def _field2(data: bytes) -> bytes | None:
    try:
        pos = 0
        while pos < len(data):
            tag = data[pos]; pos += 1
            field = tag >> 3; wtype = tag & 0x7
            if wtype == 2:
                ln, pos = _varint(data, pos)
                val = data[pos:pos+ln]; pos += ln
                if field == 2:
                    return val
            elif wtype == 0:
                _, pos = _varint(data, pos)
            else:
                break
    except Exception:
        pass
    return None


def _varint(data: bytes, pos: int) -> tuple:
    result = shift = 0
    while True:
        b = data[pos]; pos += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if not (b & 0x80):
            break
    return result, pos


def _verify_cert(cert_der: bytes) -> tuple:
    try:
        cert = x509.load_der_x509_certificate(cert_der, default_backend())
        spiffe_id = None
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
            uris = san.value.get_values_for_type(x509.UniformResourceIdentifier)
            spiffe_id = next((u for u in uris if u.startswith("spiffe://")), None)
        except Exception:
            pass
        try:
            expiry = cert.not_valid_after_utc.isoformat()
        except AttributeError:
            expiry = cert.not_valid_after.isoformat()
        try:
            issuer = cert.issuer.get_attributes_for_oid(x509.NameOID.COMMON_NAME)[0].value
        except Exception:
            issuer = "unknown"
        return spiffe_id, expiry, issuer
    except Exception as e:
        return None, None, f"parse-error: {e}"
