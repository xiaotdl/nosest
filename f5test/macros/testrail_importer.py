# -*- coding: utf-8 -*-
'''
Created on Apr 25, 2017

@author: jono
'''
from f5test.macros.base import Macro
from f5test.base import AttrDict, enum
from f5test.interfaces.testrail import TestRailInterface

import logging
import mysql.connector
import json
from jinja2 import meta


LOG = logging.getLogger(__name__)
__version__ = '1.1'

TESTRAIL = AttrDict({
    'testrail_user': '<email>',
    'testrail_key': '<key>',
    'url': 'http://<address>',
    'project': 'Demo',
    'suite': 'TS1'
})
TC_TYPE = enum(automated=3, other=7)
TEMPLATE = enum(text=1, steps=2, exploratory=3)
PRIORITY = enum(medium=2)
PRODUCT = enum(bigip=1, bigiq=2, em=3)
# STATUS = enum(passed=1, blocked=2, failed=5, skip=6)
STATUS = {'PASS': 1, 'BLOCK': 2, 'FAIL': 5, 'ERROR': 5, 'SKIP': 6}
STATUS_JSON = {'PASSED': 1, 'BLOCKED??': 2, 'FAIL': 5, 'ERROR': 5, 'SKIP': 6}


class ReconstituedTest(object):

    def __init__(self, id_):
        self.id = id_
        self.meta = AttrDict()
        self.result = None
        self.traceback = None


class TestrailFileImporter(Macro):

    def __init__(self, options, *filenames):
        self.options = AttrDict(options)
        self.filenames = filenames
        o = self.options

        o.update(TESTRAIL)
        self.case_ids = []

        super(TestrailFileImporter, self).__init__()

    def connect_testrail(self):
        self.api = TestRailInterface(self.options.url, self.options.testrail_user,
                                     self.options.testrail_key).open()

        projects = dict((x.name, x.id) for x in self.api.get_projects())
        self.project_id = projects.get(self.options.project)

        suites = dict((x.name, x.id) for x in self.api.get_suites(self.project_id))
        self.suite_id = suites.get(self.options.suite)

        self.cases = dict((x.title, x.id) for x in self.api.get_cases(self.project_id,
                                                                      self.suite_id))
        self.sections = dict((x.name, x.id) for x in self.api.get_sections(self.project_id,
                                                                           self.suite_id))

    def read_json(self, filename):
        self.output = AttrDict(json.load(file(filename)))

    def prep(self):
        #self.read_json()
        self.connect_testrail()

    def add_test_run(self, run, url):
        # LOG.info('Adding test run %s...', url)
        params = AttrDict()
        params.suite_id = self.suite_id
        #params.name = str(self.output.start)  # to be replaced
        params.name = run.get('name')
        params.description = url
        params.include_all = False
        params.case_ids = []
        return self.api.add_run(self.project_id, params)

    def get_test_metadata(self, test):
        meta = test.meta
        meta.description = ''
        return meta

    def get_or_create_section(self, test):
        """Gets or creates a section. Returns the section_id."""
        address = test.id

        context, _ = address.split(':')
        last_section = 0
        for s in context.split('.'):
            if s not in self.sections:
                params = AttrDict()
                params.name = s
                params.description = 'autogenerated'
                params.suite_id = self.suite_id
                if last_section:
                    params.parent_id = last_section
                section = self.api.add_section(self.project_id, params)
                last_section = section_id = section.id
                self.sections[section.name] = section_id
            else:
                last_section = section_id = self.sections[s]

        return section_id

    def get_or_create_case(self, test):
        """Gets or creates a test case. Returns the case_id."""
        address = test.id

        if address not in self.cases:
            section_id = self.get_or_create_section(test)
            params = AttrDict()
            params.title = address
            params.template_id = TEMPLATE.text
            params.type_id = TC_TYPE.automated
            params.priority_id = PRIORITY.medium
            params.custom_product_name = PRODUCT.bigip
            meta = test.meta
            params.custom_description = meta.description
            case = self.api.add_case(section_id, params)
            case_id = case.id
            self.cases[case.title] = case_id
        else:
            case_id = self.cases[address]

        return case_id

    def add_result(self, test):
        status_id = STATUS_JSON[test.result]
        comment = test.traceback
        case_id = self.get_or_create_case(test)
        LOG.info('Adding status %s for case %s...', status_id, case_id)
        if not case_id:
            return
        self.case_ids.append(case_id)

        params = AttrDict()
        params.case_ids = self.case_ids
        params.config_ids = []
        self.api.update_run(self.run_id, params)

        params = AttrDict()
        params.status_id = status_id
        if comment:
            params.comment = comment
#         if extra:
#             params.update(extra)
#         elapsed = int(time.time() - self.started_at)
#         if elapsed:
#             params.elapsed = "%ds" % elapsed
        return self.api.add_result_for_case(self.run_id, case_id, params)

    def setup(self):
        # print self.cases

        for filename in self.filenames:
            self.read_json(filename)
            run = self.add_test_run(self.output, self.output.url)
            self.run_id = run.id
            LOG.info('Test run URL: %s', run.url)
            # print (run_id, test_run)
            #self.cursor.execute('SELECT * from tests WHERE run_id = %s', (run_id,))
            
            for result in self.output.results:
                test = ReconstituedTest(result.name)
                #test.id = result.name
                test.result = result.status
                test.traceback = result.traceback
                test.start = result.start
                test.meta.author = result.author
                test.meta.rank = result.rank
                test.meta.description = ''
    
                # self.get_or_create_case(test)
                self.add_result(test)
    
                # print('\t' + str(row))


class TestrailImporter(Macro):

    def __init__(self, options, address=None, params=None):
        self.options = AttrDict(options)
        o = self.options
        o.port = 3307
        o.db = 'test_runs'

        o.update(TESTRAIL)
        self.case_ids = []

        super(TestrailImporter, self).__init__()

    def connect_db(self):
        o = self.options
        self.cnx = mysql.connector.connect(user=o.user, password=o.password,
                                           host=o.host, port=o.port,
                                           database=o.db)
        self.cursor = self.cnx.cursor(buffered=True)

    def connect_testrail(self):
        self.api = TestRailInterface(self.options.url, self.options.testrail_user,
                                     self.options.testrail_key).open()

        projects = dict((x.name, x.id) for x in self.api.get_projects())
        self.project_id = projects.get(self.options.project)

        suites = dict((x.name, x.id) for x in self.api.get_suites(self.project_id))
        self.suite_id = suites.get(self.options.suite)

        self.cases = dict((x.title, x.id) for x in self.api.get_cases(self.project_id,
                                                                      self.suite_id))
        self.sections = dict((x.name, x.id) for x in self.api.get_sections(self.project_id,
                                                                           self.suite_id))

    def prep(self):
        self.connect_db()
        self.connect_testrail()

    def add_test_run(self, run, meta):
        params = AttrDict()
        params.suite_id = self.suite_id
        params.name = run[3]
        params.description = run[2]
        params.include_all = False
        params.case_ids = []
        return self.api.add_run(self.project_id, params)

    def get_test_metadata(self, test):
        meta = test.meta
        meta.description = ''
        return meta

    def get_or_create_section(self, test):
        """Gets or creates a section. Returns the section_id."""
        address = test.id

        context, _ = address.split(':')
        last_section = 0
        for s in context.split('.'):
            if s not in self.sections:
                params = AttrDict()
                params.name = s
                params.description = 'autogenerated'
                params.suite_id = self.suite_id
                if last_section:
                    params.parent_id = last_section
                section = self.api.add_section(self.project_id, params)
                last_section = section_id = section.id
                self.sections[section.name] = section_id
            else:
                last_section = section_id = self.sections[s]

        return section_id

    def get_or_create_case(self, test):
        """Gets or creates a test case. Returns the case_id."""
        address = test.id

        if address not in self.cases:
            section_id = self.get_or_create_section(test)
            params = AttrDict()
            params.title = address
            params.template_id = TEMPLATE.text
            params.type_id = TC_TYPE.automated
            params.priority_id = PRIORITY.medium
            params.custom_product_name = PRODUCT.bigip
            meta = test.meta
            params.custom_description = meta.description
            case = self.api.add_case(section_id, params)
            case_id = case.id
            self.cases[case.title] = case_id
        else:
            case_id = self.cases[address]

        return case_id

    def add_result(self, test):
        status_id = STATUS[test.result]
        comment = test.traceback
        case_id = self.get_or_create_case(test)
        if not case_id:
            return
        self.case_ids.append(case_id)

        params = AttrDict()
        params.case_ids = self.case_ids
        params.config_ids = []
        self.api.update_run(self.run_id, params)

        params = AttrDict()
        params.status_id = status_id
        if comment:
            params.comment = comment
#         if extra:
#             params.update(extra)
#         elapsed = int(time.time() - self.started_at)
#         if elapsed:
#             params.elapsed = "%ds" % elapsed
        return self.api.add_result_for_case(self.run_id, case_id, params)

    def setup(self):
        # print self.cases
        self.cursor.execute('SELECT * from runs ORDER BY id DESC LIMIT %s', (self.options.last,))
        for row in self.cursor.fetchall():
            run_id = row[0]
            run_meta = json.loads(row[5])
            run = self.add_test_run(row, run_meta)
            self.run_id = run.id
            LOG.info('Test run URL: %s', run.url)
            self.cursor.execute('SELECT * from tests WHERE run_id = %s', (run_id,))
            for row in self.cursor.fetchall():
                test = ReconstituedTest(row[1])
                test.id = row[1]
                test.result = row[2]
                test.traceback = row[4]
                test.start = row[5]
                test.meta.author = row[3]
                test.meta.rank = row[7]
                test.meta.description = ''

                # self.get_or_create_case(test)
                self.add_result(test)

                LOG.info('\t' + str(row))


def main():
    import optparse
    import sys

    usage = """%prog [options] [file]...""" \
    u"""

  Examples:
  %prog --host 10.10.10.1 -u root -p password -start 100 --testrail-user user --testrail-key key
  """

    formatter = optparse.TitledHelpFormatter(indent_increment=2,
                                             max_help_position=60)
    p = optparse.OptionParser(usage=usage, formatter=formatter,
                            version="Testrail importer %s" % __version__
    )
    p.add_option("-v", "--verbose", action="store_true",
                 help="Debug logging")

    p.add_option("", "--host", metavar="HOSTNAME", type="string",
                 help="SQL Database hostname")
    p.add_option("-u", "--user", metavar="USERNAME",
                 type="string", help="SQL Username")
    p.add_option("-p", "--password", metavar="PASSWORD",
                 type="string", help="SQL Password")

#     p.add_option("", "--testrail-user", metavar="USERNAME",
#                  type="string", help="Testrail user")
#     p.add_option("", "--testrail-password", metavar="PASSWORD",
#                  type="string", help="Testrail Password")

    p.add_option("-s", "--last", metavar="INTEGER", type="int",
                 help="Import last N runs.")

    options, args = p.parse_args()

    if options.verbose:
        level = logging.DEBUG
    else:
        level = logging.INFO
        logging.getLogger('f5test').setLevel(logging.INFO)
        logging.getLogger('f5test.macros').setLevel(logging.INFO)

    LOG.setLevel(level)
    logging.basicConfig(level=level)

    if not args and not(options.host and options.user and options.password):
        p.print_version()
        p.print_help()
        sys.exit(2)

    if args:
        cs = TestrailFileImporter(options, *args)
        cs.run()
    else:
        cs = TestrailImporter(options=options)
        cs.run()




if __name__ == '__main__':
    main()
