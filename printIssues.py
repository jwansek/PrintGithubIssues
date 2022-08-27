from urllib.parse import urlparse
from dataclasses import dataclass
import datetime
import tempfile
import requests
import logging
import pickle
import pdfkit
import jinja2
import json
import cups
import os

logging.basicConfig( 
    format = "%(levelname)s\t[%(asctime)s]\t%(message)s", 
    level = logging.INFO,
    handlers=[
        logging.FileHandler("github_printer.log"),
        logging.StreamHandler()
    ])

@dataclass
class RenderedIssue(tempfile.TemporaryDirectory):

    gh_api_key: str
    issue: dict

    # this really should be done by @dataclass imo...
    def __post_init__(self):
        super().__init__()

    def __enter__(self):
        self.pdf_path = os.path.join(self.name, "out.pdf")

        with open(os.path.join(os.path.split(__file__)[0], "issue.html.j2"), "r") as f:
            jinja_template = jinja2.Template(f.read())

        gfm_html = gfm_to_html(
            self.gh_api_key, self.issue["body"], get_context_from_html_url(self.issue["html_url"])
        )
        html = jinja_template.render(**self.issue, gfm_html = gfm_html)

        pdfkit.from_string(html, self.pdf_path, options = json.loads(os.environ["WKHTMLTOPDF_OPTS"]))

        return self.pdf_path

    def __exit__(self, exc, value, tb):
        self.cleanup()

# we're not inside docker- add the environment variables from the file
if not os.path.exists("/.dockerenv") and os.path.exists("githubPrinter.env"):
    from dotenv import load_dotenv
    load_dotenv("githubPrinter.env")
    logging.info("Not being run in docker. Adding environment variables...")

cups.setUser(os.environ["CUPS_USER"])
cups.setPasswordCB(lambda a: os.environ["CUPS_PASSWD"])
cups.setServer(os.environ["CUPS_HOST"])
conn = cups.Connection()
logging.info(
    "Successfully connected to CUPS server. The avaliable printers are %s" 
    % ", ".join(conn.getPrinters().keys())
)
logging.info(
    "The printer selected to print, '%s', to has details %s" % (
        os.environ["CUPS_PRINTER"],
        json.dumps(conn.getPrinters()[os.environ["CUPS_PRINTER"]], indent=4)
    )
)

def get_user_repos(gh_api_key: str, gh_user: str):
    req = requests.get(
        "https://api.github.com/users/%s/repos" % gh_user,
        headers = {
            "Authorization": "token %s" % gh_api_key,
            "Accept": "application/vnd.github+json"
        }
    )
    if req.status_code == 200:
        repos = req.json()

        return [get_suffix_from_issues_irl(r["issues_url"]) for r in repos]
    
    else:
        logging.error("Request 'get_user_repos' '%s' failed with status code %d. Request returned %s" % (
            gh_user, req.status_code, req.text
        ))

def get_issues_for(gh_api_key: str, url_suffix: str, since: datetime.datetime) -> [dict]:
    # logging.info("Searching for issues in %s..." % url_suffix)
    req = requests.get(
        "https://api.github.com%s" % url_suffix, 
        headers = {
            "Authorization": "token %s" % gh_api_key,
            "Accept": "application/vnd.github+json"
        },
        params = {
            "since": since.replace(microsecond = 0).isoformat()
        }
    )
    if req.status_code == 200:
        return req.json()
    else:
        logging.error("Request 'get_issues_for' '%s' failed with status code %d. Request returned %s" % (
            url_suffix, req.status_code, req.text
        ))

def get_context_from_html_url(html_url: str) -> str:
    return "/".join(urlparse(html_url).path.split("/")[1:3])

def get_suffix_from_issues_irl(issues_url: str) -> str:
    return urlparse(issues_url).path.replace("{/number}", "")

def gfm_to_html(gh_api_key: str, md_text: str, context: str):
    req = requests.post(
        "https://api.github.com/markdown",
        headers = {
            "Authorization": gh_api_key,
            "Accept": "application/vnd.github+json"
        },
        json = {
            "mode": "gfm",
            "context": context,
            "text": md_text
        }
    )
    if req.status_code == 200:
        return req.text
    else:
        logging.error("Request 'gfm_to_html' failed with status code %d. Request returned %s" % (
            req.status_code, req.text
        ))

def print_file(file_path: str, actually_print: bool = True):
    if actually_print:
        conn.printFile(
            os.environ["CUPS_PRINTER"], file_path, 
            "GitHub printer job", json.loads(os.environ["CUPS_OPTS"])
        )
    logging.info("Sent file %s to the printer..." % file_path)
    logging.info("The printer queue is now %s" % json.dumps(conn.getJobs(), indent = 4))

def main():
    if not os.path.exists(".last_checked_at"):
        since = datetime.datetime(1970, 1, 1)
    else:
        with open(".last_checked_at", "rb") as f:
            since = pickle.load(f)

    logging.info("Last checked at %s" % since.replace(microsecond=0).isoformat())
    the_next_since = datetime.datetime.now()

    repos = get_user_repos(os.environ["GITHUB_TOKEN"], os.environ["GITHUB_USER"])
    logging.info("Found %i repositories to search for issues in..." % len(repos))
    issues = []
    for repo in repos:
        issues += get_issues_for(os.environ["GITHUB_TOKEN"], repo, since)

    logging.info("Found %i issues..." % len(issues))

    for issue in issues:
        logging.info("Going to try and render and print issue '%s #%d' in repo '%s'..." % (issue["title"], issue["number"], issue["html_url"]))

        with RenderedIssue(os.environ["GITHUB_TOKEN"], issue) as rendered_pdf:
            print_file(rendered_pdf, False)

    with open(".last_checked_at", "wb") as f:
        pickle.dump(the_next_since, f)

    logging.info("Run finished. Marked the last time checked as '%s'." % the_next_since.isoformat())


if __name__ == "__main__":
    main()
