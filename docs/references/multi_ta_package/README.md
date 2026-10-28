# TCP Multi-TA POC Package

Contains separate schemas and rules for TA-6, TA-10, and TA-33, an optional-TA router, AI input contract, and representative KML files.

Flow: optional UI TA selection -> focused schema extraction -> deterministic eligibility -> REVIEW_REQUIRED on unknown/conflict/mismatch -> deterministic placement.

Important: TA-33 is Stationary Lane Closure on a Divided Highway, not a generic no-shoulder case. Granite St must pass divided-highway eligibility. AUTO_APPROVED_FOR_POC_ONLY skips runtime rule approval for the demo but does not authorize field use. KML points are representative, not survey-grade.
