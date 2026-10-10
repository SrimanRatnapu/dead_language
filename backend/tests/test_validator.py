from deadlang.deliberation.validator import apply_empty_claims_rule, validate_post
from deadlang.evidence.board import EvidenceBoard
from deadlang.schemas import Challenge, Claim, EvidenceDraft, Rebuttal, SpecialistRequest, StancePost

PHRASE = "ships discreetly from our family collection"
LISTING = 'Old "carved bone" netsuke, ships from HK'


def make_board():
    b = EvidenceBoard("C-1")
    d = lambda cap, s, data: EvidenceDraft(capability=cap, summary=s, data=data, produced_by="code", specialist_name="x")
    b.add(d("listing_snapshot", "Listing L1 priced at $1,450.", {"price_usd": 1450.0}), "intake")
    b.add(d("price_check", "Median $95 (n=38); listing is 15.3x that.", {"median_usd": 95, "n": 38, "ratio": 15.3}), "intake")
    b.add(d("linked_sellers", "Sellers share a phrase.", {"shared_phrases": [PHRASE]}), "intake")
    return b


def post(claims, round_=1, stance="file", agent="buyer", **kw):
    return StancePost(agent=agent, round=round_, stance=stance, confidence=0.7,
                      claims=[Claim(text=t, evidence_ids=i) for t, i in claims], **kw)


def check(claims, **kw):
    cleaned, rej, probs = validate_post(post(claims), make_board(), LISTING, None, 1, [])
    return cleaned, rej, probs


def test_valid_claims_pass():
    cleaned, rej, _ = check([("Priced at $1,450.", ["E0"]), ("That is 15x the median.", ["E1"]),
                             (f'Two sellers use "{PHRASE}".', ["E2"]), ("See E1 for the median of $95.", ["E1"])])
    assert len(cleaned.claims) == 4 and not rej


def test_ratio_of_cited_numbers_is_accepted():
    # 1450/95 = 15.3, cited evidence holds both only when E0 and E1 are cited together
    cleaned, rej, _ = check([("About 15x the median price.", ["E0", "E1"])])
    assert not rej


def test_invented_number_rejected_with_reason():
    cleaned, rej, _ = check([("Bone netsuke often sell for $1000.", ["E1"])])
    assert not cleaned.claims
    assert rej[0].reasons == ["number 1000 not found in cited evidence E1"]


def test_quotes():
    ok, rej, _ = check([(f'The listing says "{PHRASE}".', ["E2"]), ('It says "carved bone" netsuke.', ["E0"])])
    assert len(ok.claims) == 2 and not rej                       # 2-word quote is not checked
    bad, rej, _ = check([('The seller writes "this is a genuine antique ivory piece".', ["E0"])])
    assert not bad.claims and rej[0].reasons == ["quoted text not found in cited evidence or listing"]
    curly, rej, _ = check([("The seller writes “this is a genuine antique ivory piece”.", ["E0"])])
    assert rej


def test_missing_or_absent_ids():
    _, rej, _ = check([("No price here.", [])])
    assert rej[0].reasons == ["no evidence cited"]
    _, rej, _ = check([("Something.", ["E9"])])
    assert rej[0].reasons == ["cites E9, which does not exist"]


def test_stance_change_needs_evidence():
    prev = post([("x", ["E0"])], stance="dismiss")
    cur = post([("Price is $1,450.", ["E0"])], round_=2, stance="file", rebuttal=Rebuttal(
        target_agent="defender", target_claim="x", response="r"))
    _, _, probs = validate_post(cur, make_board(), LISTING, prev, 2, [post([("x", ["E0"])], agent="defender")])
    assert "stance changed without citing the evidence that changed it" in probs
    cur = cur.model_copy(update={"changed_because": "new fact", "changed_because_evidence": ["E1"]})
    _, _, probs = validate_post(cur, make_board(), LISTING, prev, 2, [post([("x", ["E0"])], agent="defender")])
    assert not probs


def test_round2_rebuttal_rules():
    opp = [post([("The examiner could not tell the material", ["E0"])], agent="defender")]
    cur = post([("Price is $1,450.", ["E0"])], round_=2)
    _, _, probs = validate_post(cur, make_board(), LISTING, None, 2, opp)
    assert probs == ["round 2+ requires a rebuttal of the strongest opposing claim"]
    good = cur.model_copy(update={"rebuttal": Rebuttal(target_agent="defender",
                                  target_claim="examiner could not tell the material", response="r")})
    assert validate_post(good, make_board(), LISTING, None, 2, opp)[2] == []
    bad = cur.model_copy(update={"rebuttal": Rebuttal(target_agent="defender",
                                 target_claim="totally unrelated words here", response="r")})
    assert validate_post(bad, make_board(), LISTING, None, 2, opp)[2] == ["rebuttal target claim not found"]


def test_request_cap_and_self_challenge():
    reqs = [SpecialistRequest(capability="price_check", question="q", reason="r") for _ in range(3)]
    p = post([("Price is $1,450.", ["E0"])], requests=reqs, challenge=Challenge(target_agent="buyer", question="why?"))
    cleaned, _, probs = validate_post(p, make_board(), LISTING, None, 1, [])
    assert len(cleaned.requests) == 2 and cleaned.challenge is None
    assert probs == ["max 2 requests", "cannot challenge yourself"]


def test_empty_claims_rule():
    p, prob = apply_empty_claims_rule(post([], stance="file"))
    assert p.stance == "need_more" and prob
    p, prob = apply_empty_claims_rule(post([], stance="need_more"))
    assert p.stance == "need_more" and prob is None
