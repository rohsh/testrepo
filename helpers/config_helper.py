# write a class ConfigHelper that reads config/config.json and provides methods to get orgs, branches, hwsku
import json

class ConfigHelper:
    def __init__(self):
        with open("config/config.json", "r") as f:
            self.config = json.load(f)

    def get_orgs(self):
        return self.config.get("orgs", [])

    def get_branches(self):
        return self.config.get("branches", [])

    def check_org(self, org):
        orgs = self.config.get("orgs", [])
        return org in orgs

    def check_branch(self, branch):
        branches = self.config.get("branches", [])
        return branch in branches