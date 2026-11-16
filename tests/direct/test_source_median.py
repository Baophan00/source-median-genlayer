"""Direct-mode tests for SourceMedian.

    env -u PYTHONPATH -u VIRTUAL_ENV -u PYTHONHOME uv run --python 3.13 \
        --with pytest --with genlayer-test pytest tests/direct -q

The pages and the model are mocked; the contract is not.
"""

import json
import re

CONTRACT = "contracts/source_median.py"
PROMPT = r"UNTRUSTED SOURCE"
QUESTION = "How many credits does the station report?"
UNIT = "credits"

HOSTS = ["a", "b", "c", "d", "out", "bad"]
URLS = {host: f"https://station-{host}.example.org/" for host in HOSTS}
BODY = {host: f"station {host} publishes its reported reading" for host in HOSTS}


def who(addr):
    from genlayer import Address

    return str(Address(bytes(addr))).lower()


def deploy(direct_deploy):
    return direct_deploy(CONTRACT)


def register(contract, direct_vm, creator, query_id="q-1", question=QUESTION, unit=UNIT,
             tolerance=10, max_value=1000, min_sources=2, sources=None):
    direct_vm.sender = creator
    return contract.register(query_id, question, unit, tolerance, max_value, min_sources,
                              json.dumps(sources or [URLS["a"], URLS["b"]]))


def mock_read(direct_vm, values, broken=(), empty=()):
    """Mock every station page and the model answer for the stations in *values*.

    broken  the station is not mocked at all, so fetching it fails
    empty   the station renders as a page with no text on it
    values  host -> whole number, or a raw string the model answer is made of
    """
    direct_vm.clear_mocks()
    for host in HOSTS:
        if host in broken:
            continue
        body = "" if host in empty else BODY[host]
        direct_vm.mock_web(rf"station-{host}\.example\.org", {"status": 200, "body": body})
    for host, value in values.items():
        payload = value if isinstance(value, str) else json.dumps({"value": value})
        direct_vm.mock_llm(re.escape(BODY[host]), payload)


class TestRegister:
    def test_register_writes_the_query_and_the_view_reads_it_back(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        out = register(contract, direct_vm, direct_alice)

        assert out["query_id"] == "q-1"
        assert out["question"] == QUESTION
        assert out["unit"] == UNIT
        assert out["tolerance_pct"] == 10
        assert out["max_value"] == 1000
        assert out["min_sources"] == 2
        assert out["sources"] == [URLS["a"], URLS["b"]]
        assert out["creator"] == who(direct_alice)
        assert out["latest_round"] == 0

        stored = contract.get_query("q-1")
        assert stored["sources"] == [URLS["a"], URLS["b"]]
        assert stored["latest_round"] == 0
        assert contract.latest("q-1") is None
        assert contract.readings_of("q-1") == []

    def test_a_query_id_is_only_registered_once(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, "q-1")

        direct_vm.sender = direct_alice
        with direct_vm.expect_revert("is taken"):
            contract.register("q-1", QUESTION, UNIT, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))

    def test_a_query_id_is_a_short_string(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        direct_vm.sender = direct_alice

        with direct_vm.expect_revert("1 to 64 characters"):
            contract.register("", QUESTION, UNIT, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("1 to 64 characters"):
            contract.register("x" * 65, QUESTION, UNIT, 10, 1000, 2,
                              json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("1 to 64 characters"):
            contract.register(7, QUESTION, UNIT, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))

    def test_a_query_needs_two_to_eight_sources(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        direct_vm.sender = direct_alice

        with direct_vm.expect_revert("2 to 8 sources"):
            contract.register("one", QUESTION, UNIT, 10, 1000, 1, json.dumps([URLS["a"]]))
        with direct_vm.expect_revert("2 to 8 sources"):
            contract.register("nine", QUESTION, UNIT, 10, 1000, 2,
                              json.dumps([f"https://s{i}.example.org/" for i in range(9)]))

        eight = [f"https://s{i}.example.org/" for i in range(8)]
        out = contract.register("eight", QUESTION, UNIT, 10, 1000, 2, json.dumps(eight))
        assert len(out["sources"]) == 8

    def test_a_source_must_be_an_http_url_and_listed_once(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        direct_vm.sender = direct_alice

        with direct_vm.expect_revert("not an http(s) URL"):
            contract.register("bad", QUESTION, UNIT, 10, 1000, 2,
                              json.dumps([URLS["a"], "station-b.example.org"]))
        with direct_vm.expect_revert("listed twice"):
            contract.register("dup", QUESTION, UNIT, 10, 1000, 2,
                              json.dumps([URLS["a"], URLS["a"]]))

    def test_the_tolerance_the_maximum_and_the_minimum_are_ranges(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        direct_vm.sender = direct_alice

        with direct_vm.expect_revert("between 1 and 100 percent"):
            contract.register("t0", QUESTION, UNIT, 0, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("between 1 and 100 percent"):
            contract.register("t101", QUESTION, UNIT, 101, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("maximum value must be a positive"):
            contract.register("m0", QUESTION, UNIT, 10, 0, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("between 1 and 2"):
            contract.register("low", QUESTION, UNIT, 10, 1000, 0, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("between 1 and 2"):
            contract.register("high", QUESTION, UNIT, 10, 1000, 3, json.dumps([URLS["a"], URLS["b"]]))

    def test_the_question_and_the_unit_have_lengths(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        direct_vm.sender = direct_alice

        with direct_vm.expect_revert("needs a question"):
            contract.register("q", "   ", UNIT, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("longer than 600"):
            contract.register("q", "x" * 601, UNIT, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("needs a unit"):
            contract.register("q", QUESTION, "", 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))
        with direct_vm.expect_revert("longer than 32"):
            contract.register("q", QUESTION, "u" * 33, 10, 1000, 2, json.dumps([URLS["a"], URLS["b"]]))


class TestRead:
    def test_agreeing_sources_give_the_median_and_a_reliable_flag(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        mock_read(direct_vm, {"a": 42, "b": 42})
        row = contract.read("q-1")

        assert row["query_id"] == "q-1"
        assert row["round_no"] == 1
        assert row["values"] == [42, 42]
        assert row["median"] == 42
        assert row["spread"] == 0
        assert row["reliable"] is True
        assert row["source_count"] == 2
        assert contract.get_query("q-1")["latest_round"] == 1

    def test_an_outlier_beyond_the_tolerance_is_not_reliable(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, sources=[URLS["a"], URLS["b"], URLS["out"]])

        mock_read(direct_vm, {"a": 42, "b": 42, "out": 97})
        row = contract.read("q-1")

        assert row["values"] == [42, 42, 97]
        assert row["median"] == 42
        assert row["spread"] == 55
        assert row["reliable"] is False

    def test_an_even_count_of_values_takes_the_floor_average(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice,
                 sources=[URLS["a"], URLS["b"], URLS["c"], URLS["d"]])

        mock_read(direct_vm, {"a": 10, "b": 20, "c": 30, "d": 41})
        row = contract.read("q-1")

        assert row["values"] == [10, 20, 30, 41]
        assert row["median"] == 25
        assert row["spread"] == 31

    def test_a_broken_source_is_skipped_and_the_read_survives(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice,
                 sources=[URLS["a"], URLS["b"], URLS["c"]], min_sources=2)

        mock_read(direct_vm, {"a": 42, "b": 42}, broken=("c",))
        row = contract.read("q-1")

        assert row["values"] == [42, 42]
        assert row["source_count"] == 2
        assert row["median"] == 42
        assert row["reliable"] is True

    def test_falling_below_min_sources_reverts_and_stores_nothing(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, min_sources=2)

        mock_read(direct_vm, {"a": 42}, broken=("b",))
        with direct_vm.expect_revert("only 1 of 2 sources"):
            contract.read("q-1")

        assert contract.readings_of("q-1") == []
        assert contract.latest("q-1") is None
        assert contract.get_query("q-1")["latest_round"] == 0
        assert contract.stats()["readings"] == 0

    def test_one_usable_source_is_enough_when_min_sources_is_one(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, min_sources=1)

        mock_read(direct_vm, {"a": 42}, broken=("b",))
        row = contract.read("q-1")

        assert row["values"] == [42]
        assert row["source_count"] == 1
        assert row["median"] == 42
        assert row["spread"] == 0
        assert row["reliable"] is True

    def test_a_page_with_nothing_to_read_is_skipped(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, min_sources=1)

        mock_read(direct_vm, {"a": 42}, empty=("b",))
        row = contract.read("q-1")

        assert row["source_count"] == 1
        assert row["median"] == 42

    def test_a_value_above_the_maximum_is_skipped(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, max_value=100, min_sources=1)

        mock_read(direct_vm, {"a": 42, "b": 5000})
        row = contract.read("q-1")
        assert row["source_count"] == 1 and row["median"] == 42

        register(contract, direct_vm, direct_alice, "q-2", min_sources=2, max_value=100)
        mock_read(direct_vm, {"a": 42, "b": 5000})
        with direct_vm.expect_revert("only 1 of 2 sources"):
            contract.read("q-2")

    def test_a_model_answer_that_is_not_json_is_skipped(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, min_sources=1)

        mock_read(direct_vm, {"a": 42, "b": "I cannot say"})
        row = contract.read("q-1")
        assert row["source_count"] == 1 and row["median"] == 42

        mock_read(direct_vm, {"a": "{\"value\": 12", "b": 42})
        row = contract.read("q-1")
        assert row["source_count"] == 1 and row["median"] == 42

    def test_reading_twice_accumulates_rounds(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        mock_read(direct_vm, {"a": 42, "b": 42})
        first = contract.read("q-1")
        mock_read(direct_vm, {"a": 43, "b": 43})
        second = contract.read("q-1")

        assert first["round_no"] == 1 and first["median"] == 42
        assert second["round_no"] == 2 and second["median"] == 43

        rows = contract.readings_of("q-1")
        assert [r["round_no"] for r in rows] == [1, 2]
        assert contract.latest("q-1")["round_no"] == 2
        assert contract.get_query("q-1")["latest_round"] == 2

    def test_an_unknown_query_cannot_be_read(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        with direct_vm.expect_revert("no such query"):
            contract.read("missing")


class TestSources:
    def test_only_the_creator_changes_the_source_list(self, direct_vm, direct_deploy, direct_alice, direct_bob):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        direct_vm.sender = direct_bob
        with direct_vm.expect_revert("only the creator adds"):
            contract.add_source("q-1", URLS["c"])
        with direct_vm.expect_revert("only the creator removes"):
            contract.remove_source("q-1", URLS["b"])

        direct_vm.sender = direct_alice
        assert contract.add_source("q-1", URLS["c"])["sources"] == [URLS["a"], URLS["b"], URLS["c"]]
        assert contract.remove_source("q-1", URLS["b"])["sources"] == [URLS["a"], URLS["c"]]

    def test_a_query_keeps_two_to_eight_sources(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        direct_vm.sender = direct_alice
        for host in ["c", "d", "out", "bad"]:
            contract.add_source("q-1", URLS[host])
        assert len(contract.get_query("q-1")["sources"]) == 6

        assert len(contract.add_source("q-1", "https://s7.example.org/")["sources"]) == 7
        assert len(contract.add_source("q-1", "https://s8.example.org/")["sources"]) == 8
        with direct_vm.expect_revert("at most 8 sources"):
            contract.add_source("q-1", "https://s9.example.org/")

        with direct_vm.expect_revert("already listed"):
            contract.add_source("q-1", URLS["a"])

        for host in ["c", "d", "out", "bad", "s7", "s8"]:
            contract.remove_source("q-1", URLS[host] if host in URLS else f"https://{host}.example.org/")
        assert contract.get_query("q-1")["sources"] == [URLS["a"], URLS["b"]]
        with direct_vm.expect_revert("at least 2 sources"):
            contract.remove_source("q-1", URLS["b"])

    def test_a_source_that_is_not_listed_cannot_be_removed(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice)

        direct_vm.sender = direct_alice
        with direct_vm.expect_revert("not listed"):
            contract.remove_source("q-1", URLS["c"])
        with direct_vm.expect_revert("not an http(s) URL"):
            contract.remove_source("q-1", "station-c.example.org")


class TestViews:
    def test_latest_and_readings_of(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, "q-1")
        register(contract, direct_vm, direct_alice, "q-2")

        assert contract.latest("q-2") is None
        mock_read(direct_vm, {"a": 10, "b": 20})
        contract.read("q-2")
        mock_read(direct_vm, {"a": 11, "b": 21})
        contract.read("q-2")

        assert [r["round_no"] for r in contract.readings_of("q-2")] == [1, 2]
        assert contract.latest("q-2")["median"] == 16
        assert contract.readings_of("q-1") == []

    def test_list_queries_is_newest_first(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        register(contract, direct_vm, direct_alice, "q-a")
        register(contract, direct_vm, direct_alice, "q-b")
        register(contract, direct_vm, direct_alice, "q-c")

        listed = contract.list_queries(0, 10)
        assert [q["query_id"] for q in listed] == ["q-c", "q-b", "q-a"]
        assert [q["query_id"] for q in contract.list_queries(1, 10)] == ["q-b", "q-a"]
        assert contract.list_queries(0, 2)[0]["query_id"] == "q-c"

    def test_stats_counts_queries_and_readings(self, direct_vm, direct_deploy, direct_alice):
        contract = deploy(direct_deploy)
        assert contract.stats() == {"queries": 0, "readings": 0, "reliable": 0}

        register(contract, direct_vm, direct_alice, "q-1")
        register(contract, direct_vm, direct_alice, "q-2")
        assert contract.stats() == {"queries": 2, "readings": 0, "reliable": 0}

        mock_read(direct_vm, {"a": 42, "b": 42})
        contract.read("q-1")
        mock_read(direct_vm, {"a": 42, "b": 97})
        contract.read("q-2")

        assert contract.stats() == {"queries": 2, "readings": 2, "reliable": 1}
