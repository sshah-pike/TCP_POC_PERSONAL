"""Write every part hash and the pack hash into rule_pack/pack.json, then load and validate the pack.

Run after editing any rule-pack file: python scripts/seal_rule_pack.py
"""
import sys
from tcp_planner.rules.rule_pack_store import JsonRulePackStore, seal
from tcp_planner.rules.rule_pack_validator import validate


def main():
    h = seal()
    rep = validate(JsonRulePackStore().load(validate_pack=False))
    for e in rep.errors: print("ERROR", e)
    print(f"pack hash {h}; {len(rep.errors)} errors; {len(rep.unsourced)} unsourced; {len(rep.interpretations)} interpretations")
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(main())
