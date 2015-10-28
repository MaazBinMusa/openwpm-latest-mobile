from urlparse import urlparse
from netlib.odict import ODictCaseless
import sqlite3
import json
import time
import os

# This should be the modified Cookie.py included
# the standard lib Cookie.py has many bugs
import Cookie

#Potential formats for expires timestamps
DATE_FORMATS = ['%a, %d-%b-%Y %H:%M:%S %Z','%a, %d %b %Y %H:%M:%S %Z',
                '%a, %d-%b-%y %H:%M:%S %Z','%a, %d %b %y %H:%M:%S %Z',
                '%a, %d-%m-%Y %H:%M:%S %Z','%a, %d %m %Y %H:%M:%S %Z',
                '%a, %d-%m-%y %H:%M:%S %Z','%a, %d %m %y %H:%M:%S %Z']
def select_date_format(date_string):
    """ Try different formats for date and output a standard form accepted by sqlite3 """
    if date_string == '' or date_string == '0':
        return None
    else:
        for date_format in DATE_FORMATS:
            try:
                time_obj = time.strptime(date_string, date_format)
                break
            except ValueError:
                if date_format == DATE_FORMATS[len(DATE_FORMATS)-1]:
                    return None
                pass

        # time.strftime() doesn't work for years < 1900
        if time_obj.tm_year >= 1900:
            return time.strftime("%Y-%m-%d %H:%M:%S", time_obj)
        else:
            return None

def get_path(path_string, url):
    """ Parse path. Defaults to the path of the request URL that generated the
        Set-Cookie response, up to, but not including, the right-most / """
    if path_string == '':
        path = urlparse(url).path
        if path == '':
            return '/'
        path = os.path.split(path)[0]
        return path
    else:
        return path_string

def get_domain(domain_string, url):
    """
    Domains are parsed in the same style as Firefox parses them. This is NOT
    consistent across browsers. See: http://erik.io/blog/2014/03/04/definitive-guide-to-cookie-domains/
    The Firefox implementation is given in nsCookieService::CheckDomain.
    See: https://dxr.mozilla.org/mozilla-central/search?q=nsCookieService%3A%3ACheckDomain

    It can be summarized as:
      1. If a domain is given  -->  prepend a '.' if one does not exist
      2. If no domain is given -->  get hostname from request url
                                    and save without a prepended '.'

    Domains with a prepended '.' are "domain cookies" and will be sent to all
    subdomains of that domain. Domains without a '.' are not, and will only be
    sent to hostnames that are exact matches (no subdomains). This should match
    the cookies seen in our scans of cookies.sqlite.
    """
    if domain_string == '':
        domain_string = urlparse(url).hostname
    elif domain_string[0] != '.':
        domain_string = '.' + domain_string
    return domain_string

def parse_cookie_attributes(cookie, key, url, http_type):
    """
    Extract/Format each attribute of cookie
    path is set according to RFC2109 when blank
    See: http://tools.ietf.org/html/rfc2109#section-4.3.1
    domain is set according to Firefox spec
    """
    if http_type == 'response':
        domain = get_domain(cookie[key]['domain'], url)
        path = get_path(cookie[key]['path'], url)
        expires = select_date_format(cookie[key]['expires'])
        max_age = cookie[key]['max-age'] if cookie[key]['max-age'] != '' else None
        httponly = True if cookie[key]['httponly'] == True else False
        secure = True if cookie[key]['secure'] == True else False
        comment = cookie[key]['comment'] if cookie[key]['comment'] != '' else None
        version = cookie[key]['version'] if cookie[key]['version'] != '' else None
        return (domain, path, expires, max_age, httponly, secure, comment, version)

    elif http_type == 'request':
        return (None, None, None, None, None, None, None, None)

def parse_cookies(cookie_string, verbose, url = None, http_type = 'response'):
    """ Parses the cookie string from an HTTP header into a query
        query = (name, value, domain, path, expires, max-age, httponly, secure, comment, version)
    """
    queries = list()
    try:
        if type(cookie_string) == unicode:
            cookie_string = cookie_string.encode('utf-8')
        cookie = Cookie.BaseCookie(cookie_string) # requires str type
        for key in cookie.keys():
            name = unicode(key, 'utf8')
            value = unicode(cookie[key].coded_value, 'utf8')
            attrs = parse_cookie_attributes(cookie, key, url, http_type)
            query = (name, value)+attrs
            queries.append(query)
    except Cookie.CookieError, e:
        if verbose: print "[ERROR] - Malformed cookie string"
        if verbose: print "--------- " + cookie_string
        if verbose: print e
        pass
    return queries

def build_http_cookie_table(database, verbose=False):
    """ Extracts all http-cookie data from HTTP headers and generates a new table """
    con = sqlite3.connect(database)
    cur1 = con.cursor()
    cur2 = con.cursor()

    cur1.execute("CREATE TABLE IF NOT EXISTS http_cookies ( \
                    id INTEGER PRIMARY KEY AUTOINCREMENT, \
                    crawl_id INTEGER NOT NULL, \
                    header_id INTEGER NOT NULL, \
                    http_type VARCHAR(10) NOT NULL, \
                    name VARCHAR(200) NOT NULL, \
                    value TEXT NOT NULL, \
                    domain VARCHAR(500), \
                    path VARCHAR(500), \
                    expires DATETIME, \
                    max_age REAL, \
                    httponly BOOLEAN, \
                    secure BOOLEAN, \
                    comment VARCHAR(200), \
                    version VARCHAR(100), \
                    accessed DATETIME);")
    con.commit()

    # Parse http request cookies
    commit = 0
    last_commit = 0
    cur1.execute("SELECT id, crawl_id, headers, time_stamp FROM http_requests \
                    WHERE id NOT IN (SELECT header_id FROM http_cookies)")
    row = cur1.fetchone()
    while row is not None:
        req_id, crawl_id, header_str, time_stamp = row
        header = ODictCaseless()
        header.load_state(json.loads(header_str))
        for cookie_str in header['Cookie']:
            queries = parse_cookies(cookie_str, verbose, http_type = 'request')
            for query in queries:
                cur2.execute("INSERT INTO http_cookies \
                            (crawl_id, header_id, http_type, name, \
                            value, domain, path, expires, max_age, \
                            httponly, secure, comment, version, accessed) \
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (crawl_id, req_id, 'request')+query+(time_stamp,))
                commit += 1
        if commit % 10000 == 0 and commit != 0 and commit != last_commit:
            last_commit = commit
            con.commit()
            if verbose: print str(commit) + " Cookies Processed"
        row = cur1.fetchone()
    con.commit()
    print "Processing HTTP Request Cookies Complete"

    # Parse http response cookies
    commit = 0
    last_commit = 0
    cur1.execute("SELECT id, crawl_id, url, headers, time_stamp FROM http_responses \
                    WHERE id NOT IN (SELECT header_id FROM http_cookies)")
    row = cur1.fetchone()
    while row is not None:
        resp_id, crawl_id, req_url, header_str, time_stamp = row
        header = ODictCaseless()
        header.load_state(json.loads(header_str))
        for cookie_str in header['Set-Cookie']:
            queries = parse_cookies(cookie_str, verbose, url = req_url, http_type = 'response')
            for query in queries:
                cur2.execute("INSERT INTO http_cookies \
                            (crawl_id, header_id, http_type, name, \
                            value, domain, path, expires, max_age, \
                            httponly, secure, comment, version, accessed) \
                            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (crawl_id, resp_id, 'response')+query+(time_stamp,))
                commit += 1
        if commit % 10000 == 0 and commit != 0 and commit != last_commit:
            last_commit = commit
            con.commit()
            if verbose: print str(commit) + " Cookies Processed"
        row = cur1.fetchone()
    con.commit()
    print "Processing HTTP Response Cookies Complete"
    con.close()

if __name__=='__main__':
    import sys
    build_http_cookie_table(sys.argv[1], verbose=True)