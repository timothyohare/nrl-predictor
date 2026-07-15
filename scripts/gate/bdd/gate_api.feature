Feature: Gate API read path
  The booted API serves the joined read path correctly for the seeded round
  (see local_setup.py — round 12, with one superseded generation and one
  FAILED row that must never surface).

  Scenario: Health endpoint reports ok
    When I GET "/health"
    Then the response status is 200
    And the response field "status" equals "ok"

  Scenario: Seeded round returns only the surviving OK predictions
    When I GET "/predictions/12"
    Then the response status is 200
    And the response is a list of exactly 2 predictions
    And the predictions are sorted by matchId

  Scenario: Most recent OK generation wins for a superseded match
    When I GET "/predictions/12"
    Then prediction "round-12-panthers-v-broncos" field "predicted_winner" equals "Panthers"

  Scenario: Played match carries the result join with scores
    When I GET "/predictions/12"
    Then prediction "round-12-panthers-v-broncos" result winner is "Panthers"
    And prediction "round-12-panthers-v-broncos" result homeScore is 28

  Scenario: Played match carries retrospective and odds joins
    When I GET "/predictions/12"
    Then prediction "round-12-panthers-v-broncos" has a retrospective verdict
    And prediction "round-12-panthers-v-broncos" market favourite is "Panthers"

  Scenario: Agreement with the market is not an outlier
    When I GET "/predictions/12"
    Then prediction "round-12-panthers-v-broncos" outlier flag is false

  Scenario: Unplayed match has no result join
    When I GET "/predictions/12"
    Then prediction "round-12-storm-v-eels" has no result join

  Scenario: Disagreement with the market flags an outlier
    When I GET "/predictions/12"
    Then prediction "round-12-storm-v-eels" outlier flag is true

  Scenario: Unseeded round returns 404
    When I GET "/predictions/99"
    Then the response status is 404

  Scenario: Unknown route returns 404
    When I GET "/no-such-route"
    Then the response status is 404

  Scenario: Responses declare a JSON content type
    When I GET "/health"
    Then the response content type is JSON
