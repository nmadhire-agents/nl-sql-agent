from nl_sql_agent.sql_safety import validate_readonly_sql


def test_allows_select_and_with() -> None:
    assert validate_readonly_sql("select 1").ok
    assert validate_readonly_sql("with x as (select 1 as a) select a from x").ok


def test_rejects_write_and_multi_statement() -> None:
    assert not validate_readonly_sql("delete from users").ok
    assert not validate_readonly_sql("select 1; drop table users").ok
    assert not validate_readonly_sql("pragma table_info(users)").ok

