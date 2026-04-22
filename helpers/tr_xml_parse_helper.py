import re
import json
import xml.etree.ElementTree as ET
import hashlib
import traceback
from datetime import datetime, timezone

class XmlHelper:
    @staticmethod
    def read_xml_file(file_path):
        """Read an XML file and return its contents as tree."""
        try:
            tree = ET.parse(file_path)
            root = tree.getroot()
            return (True, root)
        except Exception as e:
            print(f"Error reading xml file {file_path}: {e}")
            return (False, None)

    @staticmethod
    def xml_to_dict(element):
        """
        Converts an XML element and its children to a dictionary.
        :param element: The XML element to convert.
        :return: A dictionary representation of the XML element.
        """
        def _element_to_dict(element):
            node = {}
            # Convert element attributes to dictionary
            if element.attrib:
                node.update(element.attrib)
            # Convert element children to dictionary
            for child in element:
                child_dict = _element_to_dict(child)
                if child.tag not in node:
                    node[child.tag] = child_dict
                else:
                    if not isinstance(node[child.tag], list):
                        node[child.tag] = [node[child.tag]]
                    node[child.tag].append(child_dict)
            # Add element text to dictionary
            if element.text and element.text.strip():
                node["text"] = element.text.strip()
            return node
        return {element.tag: _element_to_dict(element)}


class TrXmlHelper:
    def parse_timestamp_flexible(self, timestamp_str, format_base):
        """
        Parse timestamp that may or may not have timezone offset (+00:00, +05:02, etc.)
        Returns formatted string "%Y/%m/%d %H:%M"
        """
        # Try parsing with timezone offset first
        try:
            # Handle timezone offset like +00:00 or -05:30
            if '+' in timestamp_str or timestamp_str.count('-') > 2:
                # Remove the timezone offset (last 6 characters: +00:00 or -05:30)
                timestamp_without_tz = timestamp_str[:-6]
                return datetime.strptime(timestamp_without_tz, format_base).strftime("%Y/%m/%d %H:%M")
        except Exception:
            pass

        # Try parsing without timezone offset
        try:
            return datetime.strptime(timestamp_str, format_base).strftime("%Y/%m/%d %H:%M")
        except Exception as e:
            raise ValueError(f"Unable to parse timestamp '{timestamp_str}' with format '{format_base}': {e}")

    def get_results_record_time(self,tr_attributes):
        # Extract date from time string (format: "2026/04/19 14:35")
        date_str = tr_attributes["time"].split(" ")[0]
        # Parse the date
        date_obj = datetime.strptime(date_str, "%Y/%m/%d")
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        # Calculate week of month (1-5)
        # Week 1 starts on the 1st of the month, week 2 starts on the 8th of the month, etc.
        week_of_month = ((day - 1) // 7) + 1 if day > 7 else 1

        # Return in format: YYYY/MM/weekN where N is 1-5
        return f"{year}/{month:02d}/week{week_of_month}"

    def get_normalized_testbed_string(self, testbed):
        try:
            expected_format = r"^testbed\d+$"
            if re.match(expected_format, testbed):
                return testbed

            # Use SHA256 for deterministic hashing across runs
            hash_obj = hashlib.sha256(testbed.encode('utf-8'))
            hash_num = int(hash_obj.hexdigest(), 16) % 10001
            normalized_testbed = f"testbed{hash_num}"
            #print(f"Normalized testbed '{testbed}' to '{normalized_testbed}'")
            return normalized_testbed
        except Exception as e:
            print(f"Error normalizing testbed '{testbed}': {e}")
            return "testbedNA"

    def get_tr_attributes_v1(self, org, tr_file, sku_map=None):
        """
        {
            "format": "str",
            "org": "str",
            "branch": "str",
            "os_version": "str",
            "testbed": "str",
            "duration": "float",
            "error_testcases": "int",
            "failed_testcases": "int",
            "skipped_testcases": "int",
            "total_testcases": "int",
            "topology": "str",
            "platform": "str",
            "file": "str",
            "testcase_statuses": "list[tuple[str, str]]",
            "time": "str"
        }
        """
        attributes = {}
        sku_map = sku_map or {}

        try:
            success, root = XmlHelper.read_xml_file(tr_file)
            if not success:
                return (False, attributes)

            tr_dict = XmlHelper.xml_to_dict(root)
            #print(json.dumps(tr_dict, indent=4))
            testsuite = tr_dict["testsuites"]["testsuite"]

            attributes["format"] = "v1"
            attributes["org"] = org
            attributes["time"] = None
            attributes["file"] = None
            if "timestamp" in testsuite:
                attributes["time"] = self.parse_timestamp_flexible(testsuite["timestamp"], "%Y-%m-%dT%H:%M:%S.%f")
            start_time = None
            record_time = datetime.now(timezone.utc).strftime("%Y/%m/%d %H:%M")
            attributes["branch"] = ""
            attributes["os_version"] = ""
            attributes["testbed"] = "testbedNA"
            attributes["duration"] = round(float(testsuite["time"]), 1)

            num_skipped = int(testsuite["skipped"])
            num_errored = int(testsuite["errors"])
            num_failed = int(testsuite["failures"])
            num_testlets = int(testsuite["tests"])

            attributes["error_testcases"] = num_errored
            attributes["failed_testcases"] = num_failed
            attributes["skipped_testcases"] = num_skipped
            attributes["total_testcases"] = num_testlets

            testbed_name = None
            if "properties" in testsuite:
                # Handle both single property (dict) and multiple properties (list)
                properties = testsuite["properties"]["property"]
                if not isinstance(properties, list):
                    properties = [properties]

                for p in properties:
                    if p["name"] == "topology":
                        attributes["topology"] = p["value"]
                    if p["name"] == "testbed":
                        testbed_name = p["value"]
                        attributes["testbed"] = self.get_normalized_testbed_string(p["value"])
                    if p["name"] == "os_version":
                        attributes["os_version"] = p["value"].split(".")[-1]
                        attributes["branch"] = p["value"].split(".")[0]
                    if p["name"] == "hwsku":
                        hwsku = p["value"]
                        if hwsku not in sku_map:
                            print(f"Error: hwsku '{hwsku}' not in {sku_map}")
                            return (False, attributes)
                        attributes["hwsku"] = sku_map[hwsku]
            else:
                attributes["topology"] = "NA"

            testcases_to_add = []
            testcase_statuses = {}
            if "testcase" in testsuite:
                if not isinstance(testsuite.get("testcase"), list):
                    testcases = [testsuite["testcase"]]
                else:
                    testcases = testsuite["testcase"]

                for testcase in testcases:
                    attributes["file"] = testcase["file"]
                    testcase_name = testcase["name"]

                    # Normalize testbed names in testcase names ONLY if they match the suite's testbed
                    # Test parameters may legitimately contain testbed identifiers as part of test logic
                    # (e.g., testing upgrade paths between testbeds), so we should NOT normalize those.
                    # We only normalize when the testbed name from properties appears in the test name.
                    if testbed_name:
                        # Use word boundary regex to avoid partial replacements
                        # This ensures we only replace complete testbed names, not substrings
                        testbed_pattern = re.escape(testbed_name)
                        normalized_testbed = self.get_normalized_testbed_string(testbed_name)
                        # Replace only whole word matches to avoid replacing parts of other testbed names
                        testcase_name = re.sub(r'\b' + testbed_pattern + r'\b', normalized_testbed, testcase_name)
                    if "skipped" in testcase:
                        testcase_statuses[testcase_name] = "SKIP"
                    elif "error" in testcase:
                        if testcase_statuses.get(testcase_name) != "FAIL":
                            testcase_statuses[testcase_name] = "ERROR"
                    elif "failure" in testcase:
                        testcase_statuses[testcase_name] = "FAIL"
                    else:
                        if testcase_statuses.get(testcase_name) != "FAIL" and testcase_statuses.get(testcase_name) != "ERROR":
                            testcase_statuses[testcase_name] = "PASS"
                    try:
                        # Handle both single property (dict) and multiple properties (list)
                        tc_properties = testcase["properties"]["property"]
                        if not isinstance(tc_properties, list):
                            tc_properties = [tc_properties]

                        for prop in tc_properties:
                            if not start_time and prop["name"] == "start":
                                start_time = self.parse_timestamp_flexible(prop["value"], "%Y-%m-%d %H:%M:%S.%f")
                                break
                    except KeyError:
                        pass
            else:
                print("No testcase in testsuite")

            # Define desired status order
            order = {"FAIL": 0, "ERROR": 1, "PASS": 2, "SKIP": 3}
            # Convert dict to list of tuples and sort by custom order
            sorted_testcases = sorted(
                testcase_statuses.items(),
                key=lambda item: order.get(item[1], 99)
            )
            attributes["testcase_statuses"] = sorted_testcases

            if not attributes["time"]:
                if start_time:
                    attributes["time"] = start_time
                if not attributes["time"]:
                    attributes["time"] = record_time

        except Exception as e:
            # print stack trace
            traceback.print_exc()
            print(f"An error occurred in get_tr_attributes(): {e}")
            return (False, attributes)
        return (True, attributes)
