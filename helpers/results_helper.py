import click
import json
import subprocess
import os
import re
import traceback
import tempfile
import shutil
import zipfile
import tarfile
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from helpers.config_helper import ConfigHelper
from helpers.tr_xml_parse_helper import TrXmlHelper

class Results:
    def __init__(self, org=None, sku_map=None):
        self.org = org
        self.sku_map = sku_map
        _, self.sku_map = self.get_sku_map_dict(self.sku_map)

        self.config_helper = ConfigHelper()
        self.results_helper = ResultsHelper()
        self.tr_xml_helper = TrXmlHelper()
        self.all_orgs = self.config_helper.get_orgs()
        self.all_branches = self.config_helper.get_branches()

        self.debug = False

    def check_params(self):
        if not self.sku_map:
            return False
        return True 

    def find_tr_xml_files(self, directory):
        """Find all tr.xml files in the given directories recursively."""
        tr_files = []
        dir_path = Path(directory)
        if not dir_path.exists():
            print(f"Error: Directory {directory} does not exist, skipping...")
            return False, tr_files

        if not dir_path.is_dir():
            print(f"Error: {directory} is not a directory, skipping...")
            return False, tr_files

        # Walk through directory recursively to find tr.xml files
        for root, dirs, files in os.walk(directory):
            for file in files:
                if file.endswith(".xml"):
                    file_path = os.path.join(root, file)
                    tr_files.append(file_path)
        return True, tr_files

    def check_sku_string_format(self, sku_string):
        expected_format = rf"^{self.org}-sku\d+$"
        if not re.match(expected_format, sku_string):
            print(f"Invalid mapped sku '{sku_string}'. Expected format: sku<number> (e.g., org1-sku1, org1-sku2, org1-sku123)")
            return False
        return True

    def get_sku_map_dict(self, sku_map):
        sku_map_dict = {}
        for mapping in sku_map:
            if ':' not in mapping:
                print(f"Error: Invalid SKU mapping format '{mapping}'. Expected format: ORIGINAL:MAPPED")
                return False, None
            original, mapped = mapping.split(':', 1)

            if not self.check_sku_string_format(mapped):
                return False, None

            sku_map_dict[original.strip()] = mapped.strip()
        return True, sku_map_dict

    def is_url(self, source):
        """Check if source is a URL."""
        return source.startswith(('http://', 'https://'))

    def is_archive_file(self, filepath):
        """Check if file is a zip or tarball archive."""
        return filepath.endswith(('.zip', '.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz'))

    def is_gz_file(self, filepath):
        """Check if file is a .gz file (but not .tar.gz)."""
        return filepath.endswith('.gz') and not filepath.endswith('.tar.gz')

    def download_file_from_url(self, url):
        """Download file from URL to a temporary file and return the path."""
        try:
            # Parse URL to get filename
            parsed_url = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed_url.path)

            # Create temporary file with appropriate extension
            temp_dir = tempfile.mkdtemp(prefix='results_download_')
            temp_file_path = os.path.join(temp_dir, filename)

            click.echo(f"Downloading from URL: {url}")

            # Download the file
            with urllib.request.urlopen(url) as response:
                with open(temp_file_path, 'wb') as out_file:
                    shutil.copyfileobj(response, out_file)

            click.echo(f"  Downloaded to: {temp_file_path}")
            return temp_file_path, temp_dir
        except Exception as e:
            print(f"Error downloading file from {url}: {e}")
            if 'temp_dir' in locals() and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return None, None

    def extract_gz_file(self, gz_path):
        """Extract a .gz file to temporary directory and return the temp directory path."""
        import gzip
        temp_dir = tempfile.mkdtemp(prefix='results_extract_gz_')
        try:
            # Get the output filename (remove .gz extension)
            base_name = os.path.basename(gz_path)
            if base_name.endswith('.gz'):
                output_name = base_name[:-3]
            else:
                output_name = base_name + '.extracted'

            output_path = os.path.join(temp_dir, output_name)

            # Decompress the file
            with gzip.open(gz_path, 'rb') as f_in:
                with open(output_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)

            return temp_dir
        except Exception as e:
            print(f"Error extracting .gz file {gz_path}: {e}")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return None

    def extract_archive(self, archive_path):
        """Extract archive to temporary directory and return the temp directory path."""
        import gzip
        temp_dir = tempfile.mkdtemp(prefix='results_extract_')
        try:
            if archive_path.endswith('.zip'):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)
            elif archive_path.endswith(('.tar', '.tar.gz', '.tgz', '.tar.bz2', '.tbz2', '.tar.xz', '.txz')):
                # Try standard tarfile extraction first
                try:
                    with tarfile.open(archive_path, 'r:*') as tar_ref:
                        tar_ref.extractall(temp_dir)
                except Exception as first_error:
                    # Handle double-gzipped files (uncommon but possible)
                    if archive_path.endswith(('.tar.gz', '.tgz')):
                        print(f"  Standard extraction failed, trying double-gzip handling...")
                        try:
                            # Create a temporary file for the decompressed content
                            with tempfile.NamedTemporaryFile(delete=False, suffix='.tar') as tmp_file:
                                tmp_tar_path = tmp_file.name
                                # First decompression
                                with gzip.open(archive_path, 'rb') as f_in:
                                    content = f_in.read()
                                    # Check if it's still gzipped
                                    if content[:2] == b'\x1f\x8b':  # gzip magic number
                                        # Double-gzipped, decompress again
                                        import io
                                        with gzip.open(io.BytesIO(content), 'rb') as f_in2:
                                            tmp_file.write(f_in2.read())
                                    else:
                                        tmp_file.write(content)

                            # Now extract the tar file
                            with tarfile.open(tmp_tar_path, 'r') as tar_ref:
                                tar_ref.extractall(temp_dir)

                            # Clean up temp tar file
                            os.unlink(tmp_tar_path)
                        except Exception as second_error:
                            print(f"  Double-gzip handling also failed: {second_error}")
                            raise first_error
                    else:
                        raise first_error
            else:
                print(f"Error: Unsupported archive format for {archive_path}")
                shutil.rmtree(temp_dir)
                return None
            return temp_dir
        except Exception as e:
            print(f"Error extracting archive {archive_path}: {e}")
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            return None

    def collect_xml_files_from_sources(self, sources):
        """Collect all XML files from multiple sources (files, directories, archives, URLs)."""
        click.echo("Collecting sources..")
        all_xml_files = []
        temp_dirs = []  # Track temp directories to clean up later

        for source in sources:
            # Check if source is a URL first
            if self.is_url(source):
                # Download the file from URL
                downloaded_file, download_temp_dir = self.download_file_from_url(source)
                if not downloaded_file:
                    print(f"Error: Failed to download from URL {source}, skipping...")
                    continue

                # Track the download temp directory for cleanup
                if download_temp_dir:
                    temp_dirs.append(download_temp_dir)

                # Now process the downloaded file based on its type
                if downloaded_file.endswith('.xml'):
                    all_xml_files.append(downloaded_file)
                    click.echo(f"  Added XML file from URL")

                elif self.is_archive_file(downloaded_file):
                    temp_dir = self.extract_archive(downloaded_file)
                    if temp_dir:
                        temp_dirs.append(temp_dir)
                        # Find all XML files in extracted directory
                        for root, dirs, files in os.walk(temp_dir):
                            for file in files:
                                if file.endswith('.xml'):
                                    file_path = os.path.join(root, file)
                                    all_xml_files.append(file_path)
                        xml_files_in_archive = ([f for f in all_xml_files if temp_dir in f])
                        click.echo(f"  Extracted archive from URL: {len(xml_files_in_archive)} XML files")

                elif self.is_gz_file(downloaded_file):
                    # Handle standalone .gz files
                    temp_dir = self.extract_gz_file(downloaded_file)
                    if temp_dir:
                        temp_dirs.append(temp_dir)
                        # Find all XML files in extracted directory
                        for root, dirs, files in os.walk(temp_dir):
                            for file in files:
                                if file.endswith('.xml'):
                                    file_path = os.path.join(root, file)
                                    all_xml_files.append(file_path)
                        xml_files_in_gz = ([f for f in all_xml_files if temp_dir in f])
                        click.echo(f"  Extracted .gz from URL: {len(xml_files_in_gz)} XML files")
                else:
                    print(f"Warning: Downloaded file from {source} is not XML or archive format")

                continue  # Move to next source

            # For local sources, expand user home directory (~) and environment variables
            source = os.path.expanduser(source)
            source = os.path.expandvars(source)
            source_path = Path(source)

            # Validate source exists
            if not source_path.exists():
                print(f"Error: Source {source} does not exist, skipping...")
                continue

            # Handle XML file directly
            if source_path.is_file() and source.endswith('.xml'):
                all_xml_files.append(str(source_path))
                print(f"Added XML file: {source}")

            # Handle archive files
            elif source_path.is_file() and self.is_archive_file(source):
                if self.debug:
                    print(f"Extracting archive: {source}")
                temp_dir = self.extract_archive(source)
                if temp_dir:
                    temp_dirs.append(temp_dir)
                    # Find all XML files in extracted directory
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file.endswith('.xml'):
                                file_path = os.path.join(root, file)
                                all_xml_files.append(file_path)
                    xml_files_in_archive = ([f for f in all_xml_files if temp_dir in f])
                    click.echo(f"  Extracted {source}: {len(xml_files_in_archive)} files")

            # Handle standalone .gz files (not .tar.gz)
            elif source_path.is_file() and self.is_gz_file(source):
                if self.debug:
                    print(f"Extracting .gz file: {source}")
                temp_dir = self.extract_gz_file(source)
                if temp_dir:
                    temp_dirs.append(temp_dir)
                    # Find all XML files in extracted directory
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file.endswith('.xml'):
                                file_path = os.path.join(root, file)
                                all_xml_files.append(file_path)
                    xml_files_in_gz = ([f for f in all_xml_files if temp_dir in f])
                    click.echo(f"  Extracted .gz file {source}: {len(xml_files_in_gz)} files")

            # Handle directory
            elif source_path.is_dir():
                click.echo(f"Scanning directory: {source}")
                found_count = 0
                for root, dirs, files in os.walk(source):
                    for file in files:
                        if file.endswith('.xml'):
                            file_path = os.path.join(root, file)
                            all_xml_files.append(file_path)
                            found_count += 1
                click.echo(f"  Found {found_count} XML files in directory")

            else:
                print(f"Error: {source} is not a valid XML file, directory, or archive, skipping...")

        return all_xml_files, temp_dirs

    def results_add_from_sources(self, sources):
        """Add test results from multiple sources (XML files, directories, or archives)."""
        # Check if org is valid
        if not self.config_helper.check_org(self.org):
            print(f"Invalid org: {self.org}")
            return False

        # Collect all XML files from all sources
        tr_files, temp_dirs = self.collect_xml_files_from_sources(sources)

        if not tr_files:
            print("No XML files found in provided sources")
            # Clean up temp directories
            for temp_dir in temp_dirs:
                if os.path.exists(temp_dir):
                    shutil.rmtree(temp_dir)
            return False

        click.echo(f"Processing {len(tr_files)} files..")

        # Process all files
        add_status = []
        num_results_updates_failed = 0
        num_results_updates_success = 0
        num_results_updates_success_new = 0
        num_results_updates_success_duplicates = 0

        for tr_file in tr_files:
            status, is_duplicate, (num_results_before, num_results_after) = \
                self.results_helper.create_or_update_results_json_file(self.org, tr_file, self.sku_map)
            status_str = ""
            
            if not status:
                status_str = "Failed"
                num_results_before += 1
                num_results_after += 1
                num_results_updates_failed += 1
            else:
                num_results_updates_success += 1
                if is_duplicate:
                    num_results_updates_success_duplicates += 1
                else:
                    num_results_updates_success_new += 1

            if self.debug:
                print(f"    Processed {tr_file}: {status_str}  #records ({num_results_before} -> {num_results_after})")
            add_status.append((tr_file, status))

        failed_files = [f for f, s in add_status if not s]

        click.echo(f"Results summary..")
        click.echo(f"  Total files processed: {len(tr_files)} ({len(add_status)} ok, {len(failed_files)} failed)")
        click.echo(f"  Num updated results: {num_results_updates_success_new}")
        click.echo(f"  Num duplicates results: {num_results_updates_success_duplicates}")

        # Clean up temp directories
        for temp_dir in temp_dirs:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

        status = len(failed_files) == 0
        if not status:
            click.echo() 
            click.echo("Failed to add following files..")
            for f in failed_files:
                click.echo("    ", f)
        return status

    def results_add(self, src_dir):
        """Add test results from tr.xml files in directories."""
        # Check if org is valid
        if not self.config_helper.check_org(self.org):
            print(f"Invalid org: {self.org}")
            return False

        # Collect tr.xml files from directories
        status, tr_files = self.find_tr_xml_files(src_dir)
        if not status:
            return False

        print(f"Total files to process: {len(tr_files)}")
        # Process all files
        add_status = []
        for tr_file in tr_files:
            status, is_duplicate, (num_results_before, num_results_after) = \
                self.results_helper.create_or_update_results_json_file(self.org, tr_file, self.sku_map)
            status_str = "Failed" if not status else "Success" if not is_duplicate else "Success (duplicate)"
            print(f"    Processed {tr_file}: {status_str}  #records ({num_results_before} -> {num_results_after})")
            add_status.append((tr_file, status))

        failed_files = [f for f, s in add_status if not s]
        status = len(failed_files) == 0
        if not status:
            print("-" * 75)
            print("Failed to add following files:")
            for f in failed_files:
                print(f)
            print("-" * 75)
        return status

class ResultsHelper:
    def __init__(self):
        self.config_helper = ConfigHelper()
        self.tr_xml_helper = TrXmlHelper()
        self.results_data_lookup_num_days = 7
        self.results_data_cleanup_num_days = 180 
        self.results_data_cleanup_num_days = 8
        self.data_files_list = self.get_results_data_lookup_files_list()
        self.debug = False

    def get_results_data_lookup_files_list(self):
        files = []
        current_date = datetime.now()
        seen_weeks = set()  # Track unique weeks to avoid duplicates

        # Look through days to find all unique weeks
        for i in range(self.results_data_lookup_num_days):
            date = current_date - timedelta(days=i)
            year = date.year
            month = date.month
            day = date.day

            # Calculate week of month (1-5)
            week_of_month = ((day - 1) // 7) + 1

            week_path = str(Path(str(year)) / f"{month:02d}" / f"week{week_of_month}" / "results.json")

            # Only add if we haven't seen this week yet
            if week_path not in seen_weeks:
                seen_weeks.add(week_path)
                files.append(week_path)

        return files

    def create_results_dir_if_needed(self, org, record_time):
        try:
            org_path = Path("data") / org
            dir_path = org_path / record_time

            # Create all parent directories as needed
            dir_path.mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:
            traceback.print_exc()
            print(f"Operation failed creating directory {dir_path}: {e}")
            return False

    def create_or_update_results_json_file(self, org, tr_file, sku_map=None):
        status, tr_attributes = self.tr_xml_helper.get_tr_attributes_v1(org, tr_file, sku_map)
        if not status:
            return False, False, (0, 0)

        # Set the org after getting attributes
        tr_attributes["org"] = org

        # Convert testcase_statuses tuples to lists for JSON compatibility
        if "testcase_statuses" in tr_attributes:
            tr_attributes["testcase_statuses"] = [list(item) for item in tr_attributes["testcase_statuses"]]

        cmd = None
        try:
            record_time = self.tr_xml_helper.get_results_record_time(tr_attributes)
            if not self.create_results_dir_if_needed(org, record_time):
                return False, False, (0, 0)

            org_path = Path("data") / org
            results_json_file_path = org_path / record_time / "results.json"
            # Check if a results.json file exists in that directory.
            # If so, read it in and add the new results.  If not, create a new one.

            num_results_before = 0
            results_json_file = results_json_file_path
            if results_json_file.exists():
                results = json.loads(results_json_file.read_text())
                num_results_before = len(results)
                if tr_attributes in results:
                    # tr_attributes already exists in the results.json file
                    return True, True, (num_results_before, num_results_before)
                results.append(tr_attributes)
            else:
                results = [tr_attributes]

            results_json_file.write_text(json.dumps(results, indent=4))

            num_results_after = num_results_before + 1
            return True, False, (num_results_before, num_results_after)
        except Exception as e:
            print(f"Operation failed in writing results.json using cmd ({cmd}): {e}")
            traceback.print_exc()
            return False, False, (0, 0)

    def do_git_pull(self, org):
        cmd = None
        try:
            cmd = "git pull"
            os.system(cmd)
            return True
        except Exception as e:
            print(f"Operation failed for cmd ({cmd}): {e}")
            return False

    def do_git_validate_all_checked_out_files_are_results_json(self):
        # Validate that all the staged files are of the format
        # data/orgNNN/YYYY/MM/weekN/results.json
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=True
        )
        staged_files = result.stdout.strip().split('\n') if result.stdout.strip() else []

        # Pattern for valid results file paths
        valid_pattern = re.compile(r'^data/org\d+/\d{4}/\d{2}/week\d+/results\.json$')

        invalid_files = []
        for file_path in staged_files:
            if not valid_pattern.match(file_path):
                invalid_files.append(file_path)

        if invalid_files:
            print(f"Error: Found invalid file(s) staged for commit:")
            for file_path in invalid_files:
                print(f"  {file_path}")
            print(f"All staged files must match the format: data/orgNNN/YYYY/MM/weekN/results.json")
            return False
        return True

    def do_git_push(self, org):
        cmd = None
        try:
            cmd = f"git add ."
            os.system(cmd)

            if not self.do_git_validate_all_checked_out_files_are_results_json():
                click.echo("Invalid files staged for commit.  Aborting push.")
                return False

            # Set both author and committer to SonicTestResults
            cmd = f"git -c user.name='SonicTestResults' -c user.email='sonictestresults@sonicfoundation.dev' commit --author='SonicTestResults <sonictestresults@sonicfoundation.dev>' -m 'Updating sonic-mgmt test results for {org}'"
            os.system(cmd)

            cmd = f"git push origin main"
            os.system(cmd)
        except Exception as e:
            print(f"Operation failed for cmd ({cmd}): {e}")
            return False