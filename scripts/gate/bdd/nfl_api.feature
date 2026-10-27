Feature: NFL API read path
  The booted gate server routes /nfl/* to the NFL API Lambda (nfl.api.router),
  which serves the latest OK prediction per game for a season+week, joined to
  nfl_games for the result and the market comparison. The seeded 2026 week 8
  (see nfl_setup.py seed_api) has one superseded generation, one FAILED row and
  one orphan prediction whose game is no longer in nfl_games — none may surface.

  Background:
    Given the NFL API read-path seed is loaded

  Scenario: Health endpoint reports ok
    When I GET "/health"
    Then the response status is 200
    And the response field "status" equals "ok"

  Scenario: Seeded week returns exactly the surviving OK predictions, sorted
    When I GET "/nfl/predictions/2026/8"
    Then the response status is 200
    And the response content type is JSON
    And the response matchIds are, in order:
      | matchId                            |
      | nfl-2026-week-8-packers-v-panthers |
      | nfl-2026-week-8-jets-v-raiders     |
      | nfl-2026-week-8-broncos-v-chiefs   |
    And prediction "nfl-2026-week-8-packers-v-panthers" field "predicted_winner" equals "packers"
    And prediction "nfl-2026-week-8-packers-v-panthers" field "label" equals "Week 8"

  Scenario: Played game carries its result; unplayed game has none
    When I GET "/nfl/predictions/2026/8"
    Then prediction "nfl-2026-week-8-packers-v-panthers" result home_score is 24
    And prediction "nfl-2026-week-8-packers-v-panthers" result winner is "packers"
    And prediction "nfl-2026-week-8-broncos-v-chiefs" has no result

  Scenario: Outlier flag against the spread
    When I GET "/nfl/predictions/2026/8"
    Then prediction "nfl-2026-week-8-packers-v-panthers" is_outlier is false
    And prediction "nfl-2026-week-8-broncos-v-chiefs" is_outlier is true
    And prediction "nfl-2026-week-8-broncos-v-chiefs" market spread favourite is "chiefs"
    And prediction "nfl-2026-week-8-jets-v-raiders" has no is_outlier field

  Scenario: Unknown week is 404
    When I GET "/nfl/predictions/2026/17"
    Then the response status is 404
    And the response content type is JSON

  Scenario: Non-integer week is 400
    When I GET "/nfl/predictions/2026/eight"
    Then the response status is 400
    And the response content type is JSON

  Scenario: Current week and accuracy endpoints answer
    When I GET "/nfl/weeks/current"
    Then the response status is 200
    And the response has fields season, week, stage, label
    When I GET "/nfl/accuracy?season=2026"
    Then the response status is 200
    And the response field "n" is 1
