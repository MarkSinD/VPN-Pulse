from vpnpulse.access_policy import issuance_decision


def config(**access):
    return {
        "access": access,
        "servers": [{"id": "s1", "access": {"issuance_enabled": True, "maintenance": False}}],
    }


def test_missing_access_block_is_fail_closed():
    assert issuance_decision({"servers": []}, "s1").code == "member_registry_disabled"


def test_global_flags_fail_closed_in_dependency_order():
    assert issuance_decision(config(member_registry_enabled=True), "s1").code == "grants_disabled"
    assert issuance_decision(config(member_registry_enabled=True, grants_enabled=True), "s1").code == "issuance_disabled"


def test_server_circuit_breakers_and_success():
    enabled = config(member_registry_enabled=True, grants_enabled=True, issuance_enabled=True)
    assert issuance_decision(enabled, "missing").code == "server_not_found"
    enabled["servers"][0]["access"]["issuance_enabled"] = False
    assert issuance_decision(enabled, "s1").code == "server_issuance_disabled"
    enabled["servers"][0]["access"] = {"issuance_enabled": True, "maintenance": True}
    assert issuance_decision(enabled, "s1").code == "server_maintenance"
    enabled["servers"][0]["access"]["maintenance"] = False
    assert issuance_decision(enabled, "s1").allowed is True
