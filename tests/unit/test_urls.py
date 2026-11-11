"""Normalising offer URLs before they are saved (D-05).

The unique constraint ``uq_job_offers_url`` compares URLs as stored, so the same offer must
always be stored under the same spelling: links copied from a job board differ in letter
case, tracking parameters, fragments or a trailing slash. ``normalise_offer_url`` only
rewrites a URL that has already been validated (an ``https`` URL with a host); it does not
validate it.
"""

import pytest

from job_tracker.core.urls import normalise_offer_url

CANONICAL: str = "https://justjoin.it/job-offer/acme-python-developer"


def test_canonical_url_is_left_unchanged() -> None:
    assert normalise_offer_url(CANONICAL) == CANONICAL


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("HTTPS://JustJoin.IT/job-offer/acme", "https://justjoin.it/job-offer/acme"),
        ("https://acme.com/Careers/Python-Dev", "https://acme.com/Careers/Python-Dev"),
    ],
    ids=["scheme-and-host-lower-cased", "path-keeps-its-case"],
)
def test_only_scheme_and_host_are_lower_cased(url: str, expected: str) -> None:
    # Paths are case-sensitive on most servers, so only the case-insensitive parts change.
    assert normalise_offer_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com/jobs/python/", "https://acme.com/jobs/python"),
        ("https://acme.com/jobs/python///", "https://acme.com/jobs/python"),
        ("https://acme.com/", "https://acme.com"),
        ("https://acme.com", "https://acme.com"),
    ],
    ids=["trailing-slash", "several-trailing-slashes", "root-slash", "no-path"],
)
def test_trailing_slashes_are_removed(url: str, expected: str) -> None:
    assert normalise_offer_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com/jobs/1?utm_source=linkedin", "https://acme.com/jobs/1"),
        (
            "https://acme.com/jobs/1?utm_source=a&utm_medium=b&utm_campaign=c&utm_term=d"
            "&utm_content=e",
            "https://acme.com/jobs/1",
        ),
        ("https://acme.com/jobs/1?UTM_Source=newsletter", "https://acme.com/jobs/1"),
        ("https://acme.com/jobs/1?gclid=abc&fbclid=def", "https://acme.com/jobs/1"),
        (
            "https://www.linkedin.com/jobs/view/123?refId=abc&trackingId=def&trk=public_jobs",
            "https://www.linkedin.com/jobs/view/123",
        ),
    ],
    ids=["utm-source", "all-utm", "utm-any-case", "click-ids", "linkedin-tracking"],
)
def test_tracking_parameters_are_removed(url: str, expected: str) -> None:
    assert normalise_offer_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com/jobs?a=1&&b=2", "https://acme.com/jobs?a=1&b=2"),
        ("https://acme.com/jobs?a=1&", "https://acme.com/jobs?a=1"),
        ("https://acme.com/jobs?&utm_source=x&", "https://acme.com/jobs"),
    ],
    ids=["double-ampersand", "trailing-ampersand", "only-separators-left"],
)
def test_empty_query_parameters_are_removed(url: str, expected: str) -> None:
    assert normalise_offer_url(url) == expected


def test_query_parameter_without_a_value_is_kept() -> None:
    url = "https://acme.com/jobs?remote&utm_source=x"

    assert normalise_offer_url(url) == "https://acme.com/jobs?remote"


def test_credentials_in_the_url_are_dropped() -> None:
    # They never identify the offer, and must not end up in the database.
    url = "https://user:secret@Acme.com/jobs/1"

    assert normalise_offer_url(url) == "https://acme.com/jobs/1"


def test_other_query_parameters_are_kept_in_their_order() -> None:
    url = "https://pracuj.pl/praca/python;oferta,123?s=2&utm_source=x&id=7&lang=pl"

    assert normalise_offer_url(url) == "https://pracuj.pl/praca/python;oferta,123?s=2&id=7&lang=pl"


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://acme.com/jobs/1?", "https://acme.com/jobs/1"),
        ("https://acme.com/jobs/1#apply", "https://acme.com/jobs/1"),
        ("https://acme.com/jobs/1?utm_source=x#apply", "https://acme.com/jobs/1"),
        ("https://acme.com:443/jobs/1", "https://acme.com/jobs/1"),
        ("https://acme.com:8443/jobs/1", "https://acme.com:8443/jobs/1"),
        ("  https://acme.com/jobs/1\n", "https://acme.com/jobs/1"),
        ("https://acme.com/jobs/python%20developer", "https://acme.com/jobs/python%20developer"),
    ],
    ids=[
        "empty-query",
        "fragment",
        "tracking-and-fragment",
        "default-port",
        "other-port-kept",
        "surrounding-whitespace",
        "percent-encoding-kept",
    ],
)
def test_url_details_that_do_not_identify_the_offer_are_dropped(url: str, expected: str) -> None:
    assert normalise_offer_url(url) == expected


def test_spellings_of_one_offer_normalise_to_the_same_url() -> None:
    spellings = [
        "https://justjoin.it/job-offer/acme-python-developer",
        "https://justjoin.it/job-offer/acme-python-developer/",
        "HTTPS://JUSTJOIN.IT/job-offer/acme-python-developer",
        "https://justjoin.it:443/job-offer/acme-python-developer#about",
        "https://justjoin.it/job-offer/acme-python-developer?utm_source=newsletter&utm_medium=email",
        " https://justjoin.it/job-offer/acme-python-developer/?fbclid=abc ",
    ]

    assert {normalise_offer_url(url) for url in spellings} == {CANONICAL}


@pytest.mark.parametrize(
    "url",
    [
        CANONICAL,
        "HTTPS://Acme.com:443/Jobs/1/?utm_source=x&id=7#apply",
        "https://pracuj.pl/praca/python;oferta,123?s=2",
    ],
)
def test_normalising_twice_gives_the_same_result(url: str) -> None:
    once = normalise_offer_url(url)

    assert normalise_offer_url(once) == once
