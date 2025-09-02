from cogs.tickets.mebinu_flow import MebinuSession, QUESTIONS

def test_flow_happy_path():
    s = MebinuSession()
    assert s.next_question() == QUESTIONS[0]
    s.record("figurát"); s.next_question()
    s.record("piros"); s.next_question()
    s.record("holnap"); s.next_question()
    s.record("1000 HUF"); s.next_question()
    s.record("igen");
    assert s.next_question() is None
    summary = s.summary()
    assert "figurát" in summary and "1000" in summary
