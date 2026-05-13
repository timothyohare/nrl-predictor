def make_draw_with_results(n_matches: int = 2) -> dict:
    fixtures = []
    teams = [
        ("Panthers", "Broncos"), ("Sharks", "Storm"), ("Roosters", "Raiders"),
        ("Warriors", "Cowboys"), ("Titans", "Eels"), ("Dragons", "Bulldogs"),
        ("Knights", "Sea Eagles"), ("Rabbitohs", "Wests Tigers"),
    ]
    for i in range(n_matches):
        home, away = teams[i % len(teams)]
        fixtures.append({
            "matchCentreUrl": f"/draw/nrl-premiership/2026/round-1/{home.lower()}-v-{away.lower()}/",
            "homeTeam": {"nickName": home, "teamId": str(500000 + i), "score": 24},
            "awayTeam": {"nickName": away, "teamId": str(500100 + i), "score": 14},
            "venue": {"name": "Test Stadium"},
            "roundNumber": 1,
            "clock": {"kickOffTimeLong": "2026-03-05T09:50:00Z"},
            "matchState": "FullTime",
            "matchMode": "Post",
        })
    return {"fixtures": fixtures}
