# coding=utf-8
import locale
import unittest
import sys, os.path

sys.path.append(os.path.abspath('..'))
sys.path.append(os.path.abspath('../lib'))

import sickbeard
from sickbeard import encodingKludge as ek
from sickbeard.exceptions import ex
from sickbeard.helpers import sanitizeFileName

class EncodingTests(unittest.TestCase):
    def test_encoding(self):
        rootDir = 'C:\\Temp\\TV'
        strings = [u'Les Enfants De La T\xe9l\xe9', u'RT� One']

        sickbeard.SYS_ENCODING = None

        try:
            locale.setlocale(locale.LC_ALL, "")
            sickbeard.SYS_ENCODING = locale.getpreferredencoding()
        except (locale.Error, IOError):
            pass

        # For OSes that are poorly configured I'll just randomly force UTF-8
        if not sickbeard.SYS_ENCODING or sickbeard.SYS_ENCODING in ('ANSI_X3.4-1968', 'US-ASCII', 'ASCII'):
            sickbeard.SYS_ENCODING = 'UTF-8'

        for s in strings:
            try:
                show_dir = ek.ek(os.path.join, rootDir, sanitizeFileName(s))
                self.assertTrue(isinstance(show_dir, unicode))
            except Exception, e:
                ex(e)

if __name__ == "__main__":
    print "=================="
    print "STARTING - ENCODING TESTS"
    print "=================="
    print "######################################################################"
    suite = unittest.TestLoader().loadTestsFromTestCase(EncodingTests)
    unittest.TextTestRunner(verbosity=2).run(suite)