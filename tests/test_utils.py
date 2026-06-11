import pytest
from datetime import datetime, date, timezone, timedelta
from api_service_handler.utils import (
    generate_id, now_utc, today_utc, is_same_day, is_same_month,
    mask_key_value, validate_connection_string, parse_metadata_filter,
    format_timedelta, chunks, sanitize_provider_name
)

def test_generate_id():
    id1 = generate_id()
    id2 = generate_id()
    assert id1 != id2
    assert isinstance(id1, str)
    assert len(id1) == 36

def test_now_utc():
    now = now_utc()
    assert now.tzinfo == timezone.utc

def test_today_utc():
    today = today_utc()
    assert isinstance(today, date)

def test_is_same_day():
    d1 = date(2023, 5, 1)
    d2 = date(2023, 5, 1)
    d3 = date(2023, 5, 2)
    assert is_same_day(d1, d2) is True
    assert is_same_day(d1, d3) is False

def test_is_same_month():
    d1 = date(2023, 5, 1)
    d2 = date(2023, 5, 15)
    d3 = date(2023, 6, 1)
    assert is_same_month(d1, d2) is True
    assert is_same_month(d1, d3) is False

def test_mask_key_value():
    assert mask_key_value("sk-abcdefghijk", 8) == "sk-abcde***"
    assert mask_key_value("sk-a", 8) == "sk***"
    assert mask_key_value("s", 8) == "s***"

def test_validate_connection_string():
    assert validate_connection_string("sqlite", "sqlite:///test.db") is True
    assert validate_connection_string("sqlite", "mysql://test") is False
    assert validate_connection_string("mongodb", "mongodb://localhost") is True
    assert validate_connection_string("postgresql", "postgresql://localhost") is True
    assert validate_connection_string("postgresql", "postgres://localhost") is True

def test_parse_metadata_filter():
    metadata = {"env": "prod", "team": {"name": "backend", "id": 1}}
    assert parse_metadata_filter({"env": "prod"}, metadata) is True
    assert parse_metadata_filter({"env": "dev"}, metadata) is False
    assert parse_metadata_filter({"team.name": "backend"}, metadata) is True
    assert parse_metadata_filter({"team.id": 1}, metadata) is True
    assert parse_metadata_filter({"team.id": 2}, metadata) is False
    assert parse_metadata_filter({"nonexistent": "value"}, metadata) is False

def test_format_timedelta():
    td1 = timedelta(hours=2, minutes=30)
    assert format_timedelta(td1) == "2h 30m"
    td2 = timedelta(days=5, hours=12)
    assert format_timedelta(td2) == "5d 12h"
    td3 = timedelta(minutes=45)
    assert format_timedelta(td3) == "45m"
    td4 = timedelta(seconds=15)
    assert format_timedelta(td4) == "0m"

def test_chunks():
    lst = [1, 2, 3, 4, 5, 6, 7]
    result = list(chunks(lst, 3))
    assert result == [[1, 2, 3], [4, 5, 6], [7]]

def test_sanitize_provider_name():
    assert sanitize_provider_name(" OpenAI ") == "openai"
    assert sanitize_provider_name("Google-Gemini") == "google_gemini"
    assert sanitize_provider_name("aws bedrock") == "aws_bedrock"
