from core.log_sources import list_docker_log_sources, search_sources


class _FakeSSH:
    def __init__(self):
        self._responses = {}   # cmd substring -> (out, err, code)
        self._default = ("", "", 0)

    def route(self, substring, out="", err="", code=0):
        self._responses[substring] = (out, err, code)

    def run(self, cmd):
        for substring, result in self._responses.items():
            if substring in cmd:
                return result
        return self._default


# ---------------------------------------------------------------------------
# list_docker_log_sources
# ---------------------------------------------------------------------------

def test_list_docker_log_sources_builds_one_entry_per_container():
    ssh = _FakeSSH()
    ssh.route("docker ps -a", out="homarr\nportainer\nntfy\n")
    sources = list_docker_log_sources(ssh)
    assert set(sources.keys()) == {"Docker: homarr", "Docker: portainer", "Docker: ntfy"}
    assert sources["Docker: homarr"] == "docker logs --tail 150 homarr 2>&1"


def test_list_docker_log_sources_empty_on_failure():
    ssh = _FakeSSH()
    ssh.route("docker ps -a", out="", err="docker: command not found", code=127)
    assert list_docker_log_sources(ssh) == {}


def test_list_docker_log_sources_empty_when_no_containers():
    ssh = _FakeSSH()
    ssh.route("docker ps -a", out="", code=0)
    assert list_docker_log_sources(ssh) == {}


# ---------------------------------------------------------------------------
# search_sources
# ---------------------------------------------------------------------------

def test_search_sources_filters_case_insensitively():
    ssh = _FakeSSH()
    ssh.route("homarr", out="line one\nERROR: disk full\nline three\n")
    sources = {"Docker: homarr": "docker logs homarr"}
    results = search_sources(ssh, sources, "error")
    assert results == {"Docker: homarr": ["ERROR: disk full"]}


def test_search_sources_omits_sources_with_no_matches():
    ssh = _FakeSSH()
    ssh.route("homarr", out="all good here\n")
    ssh.route("portainer", out="also fine\n")
    sources = {"Docker: homarr": "docker logs homarr",
               "Docker: portainer": "docker logs portainer"}
    results = search_sources(ssh, sources, "error")
    assert results == {}


def test_search_sources_tolerates_one_source_failing():
    class _RaisingSSH:
        def run(self, cmd):
            if "broken" in cmd:
                raise ConnectionError("boom")
            return ("found the keyword here\n", "", 0)

    sources = {"broken": "cmd for broken source", "ok": "cmd for ok source"}
    results = search_sources(_RaisingSSH(), sources, "keyword")
    assert results == {"ok": ["found the keyword here"]}


def test_search_sources_multiple_matches_in_one_source():
    ssh = _FakeSSH()
    ssh.route("homarr", out="keyword one\nnothing\nkeyword two\n")
    sources = {"Docker: homarr": "docker logs homarr"}
    results = search_sources(ssh, sources, "keyword")
    assert results == {"Docker: homarr": ["keyword one", "keyword two"]}
