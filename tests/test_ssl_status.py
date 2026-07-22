import datetime

from core.ssl_status import check_hosts_expiry


class _FakeSSH:
    def __init__(self):
        self._responses = []  # list of (out, err, code), consumed in order

    def run(self, cmd):
        if self._responses:
            return self._responses.pop(0)
        return ("", "", 0)


def _cert_output(days_from_now):
    expiry = datetime.datetime.utcnow() + datetime.timedelta(days=days_from_now)
    not_after = expiry.strftime("%b %d %H:%M:%S %Y GMT")
    return "Not After : {}\n".format(not_after)


def test_healthy_cert_is_ok():
    ssh = _FakeSSH()
    ssh._responses = [(_cert_output(60), "", 0)]  # first connect attempt succeeds
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert len(results) == 1
    assert results[0]["status"] == "ok"
    assert results[0]["days"] > 30


def test_cert_expiring_soon_is_warn():
    ssh = _FakeSSH()
    ssh._responses = [(_cert_output(20), "", 0)]
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert results[0]["status"] == "warn"


def test_cert_nearly_expired_is_crit():
    ssh = _FakeSSH()
    ssh._responses = [(_cert_output(3), "", 0)]
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert results[0]["status"] == "crit"


def test_no_cert_after_all_fallbacks_is_error():
    ssh = _FakeSSH()
    # None of the 4 fallback connect attempts return usable output.
    ssh._responses = [("", "", 0)] * 4
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert results[0]["status"] == "error"
    assert results[0]["days"] is None


def test_falls_back_to_loopback_when_external_fails():
    ssh = _FakeSSH()
    ssh._responses = [
        ("", "", 0),                    # external host:host attempt fails
        (_cert_output(90), "", 0),      # localhost:host attempt succeeds
    ]
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert results[0]["status"] == "ok"


def test_unparseable_output_is_error():
    ssh = _FakeSSH()
    ssh._responses = [("Not After : garbage-date\n", "", 0)]
    results = check_hosts_expiry(ssh, [("example.com", "443")])
    assert results[0]["status"] == "error"
    assert "Could not parse" in results[0]["error"]


def test_multiple_hosts_checked_independently():
    ssh = _FakeSSH()
    ssh._responses = [
        (_cert_output(60), "", 0),   # host1 succeeds on first try
        ("", "", 0), ("", "", 0), ("", "", 0), ("", "", 0),  # host2 fails all 4
    ]
    results = check_hosts_expiry(ssh, [("host1.example.com", "443"),
                                       ("host2.example.com", "8443")])
    assert results[0]["status"] == "ok"
    assert results[1]["status"] == "error"
    assert results[1]["host"] == "host2.example.com"
