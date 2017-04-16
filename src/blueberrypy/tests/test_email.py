import unittest
import warnings

from email.header import decode_header

try:
    from aiosmtpd.controller import Controller  # importing third-party package
    from aiosmtpd.handlers import Mailbox       # first to get ImportError early

    import os

    from mailbox import Maildir
    from operator import itemgetter
    from tempfile import TemporaryDirectory

    class QueueController(Controller):
        def __init__(self, host, port):
            self._tmp_dir = TemporaryDirectory()
            os.rmdir(self._tmp_dir.name)
            super().__init__(handler=Mailbox(self._tmp_dir.name), hostname=host, port=port)

        def start(self):
            super().start()
            host, port, _, _ = self.server.sockets[0].getsockname()
            setattr(self.server, 'host', host)
            setattr(self.server, 'port', port)

        def stop(self):
            super().stop()
            self._tmp_dir.cleanup()

        def __del__(self):
            del self._tmp_dir

        def __iter__(self):
            return iter(sorted(self.handler.mailbox, key=itemgetter('message-id')))
except ImportError:
    from lazr.smtptest.controller import QueueController

from six import text_type

from blueberrypy import email
from blueberrypy.email import Mailer


class BaseEmailTestCase(unittest.TestCase):

    def setUp(self):
        self.controller = QueueController('localhost', 9025)
        self.controller.start()

        self._smtp_host = self.controller.server.host
        self._smtp_port = self.controller.server.port

    def tearDown(self):
        self.controller.stop()
        del self._smtp_host
        del self._smtp_port


class MailerTest(BaseEmailTestCase):

    def test_send_email(self):
        mailer = Mailer(self._smtp_host, self._smtp_port)
        body = "This is the bloody test body"
        mailer.send_email("rcpt@example.com", "from@example.com", "test subject", body)

        message = list(self.controller)[0]
        (from_str, from_cs) = decode_header(message["From"])[0]
        (to_str, to_cs) = decode_header(message["To"])[0]
        (subject_str, subject_cs) = decode_header(message["Subject"])[0]

        self.assertEqual("from@example.com", from_str)
        self.assertEqual("rcpt@example.com", to_str)
        self.assertEqual("test subject", subject_str)
        self.assertEqual(body, text_type(message.get_payload(decode=True),
                                       message.get_content_charset()))

    def test_send_html_email(self):
        mailer = Mailer(self._smtp_host, self._smtp_port)
        text = u"This is the bloody test body"
        html = u"<p>This is the bloody test body</p>"
        mailer.send_html_email("rcpt@example.com", "from@example.com", "test subject", text, html)

        message = list(self.controller)[0]
        (from_str, from_cs) = decode_header(message["From"])[0]
        (to_str, to_cs) = decode_header(message["To"])[0]
        (subject_str, subject_cs) = decode_header(message["Subject"])[0]

        self.assertEqual("from@example.com", from_str)
        self.assertEqual("rcpt@example.com", to_str)
        self.assertEqual("test subject", subject_str)
        self.assertEqual(text, text_type(message.get_payload(0).get_payload(decode=True),
                                       message.get_payload(0).get_content_charset()))
        self.assertEqual("text/plain", message.get_payload(0).get_content_type())
        self.assertEqual(html, text_type(message.get_payload(1).get_payload(decode=True),
                                       message.get_payload(1).get_content_charset()))
        self.assertEqual("text/html", message.get_payload(1).get_content_type())


class EmailModuleFuncTest(BaseEmailTestCase):

    def test_warnings(self):

        email._mailer = None

        with warnings.catch_warnings(record=True):
            warnings.simplefilter("error")
            self.assertRaises(UserWarning, email.send_email, "rcpt@example.com", "from@example.com",
                              "test subject", "test body")
            self.assertRaises(UserWarning, email.send_html_email, "rcpt@example.com",
                              "from@example.com", "test subject", "plain body", "<p>html body</p>")

    def test_send_email(self):
        email.configure({"host": self._smtp_host,
                         "port": self._smtp_port})

        body = "This is the bloody test body"
        email.send_email("rcpt@example.com", "from@example.com", "test subject", body)

        message = list(self.controller)[0]
        (from_str, from_cs) = decode_header(message["From"])[0]
        (to_str, to_cs) = decode_header(message["To"])[0]
        (subject_str, subject_cs) = decode_header(message["Subject"])[0]

        self.assertEqual("from@example.com", from_str)
        self.assertEqual("rcpt@example.com", to_str)
        self.assertEqual("test subject", subject_str)
        self.assertEqual(body, text_type(message.get_payload(decode=True),
                                       message.get_content_charset()))

    def test_send_html_email(self):
        email.configure({"host": self._smtp_host,
                         "port": self._smtp_port})

        text = u"This is the bloody test body"
        html = u"<p>This is the bloody test body</p>"
        email.send_html_email("rcpt@example.com", "from@example.com", "test subject", text, html)

        message = list(self.controller)[0]
        (from_str, from_cs) = decode_header(message["From"])[0]
        (to_str, to_cs) = decode_header(message["To"])[0]
        (subject_str, subject_cs) = decode_header(message["Subject"])[0]

        self.assertEqual("from@example.com", from_str)
        self.assertEqual("rcpt@example.com", to_str)
        self.assertEqual("test subject", subject_str)
        self.assertEqual(text, text_type(message.get_payload(0).get_payload(decode=True),
                                       message.get_payload(0).get_content_charset()))
        self.assertEqual("text/plain", message.get_payload(0).get_content_type())
        self.assertEqual(html, text_type(message.get_payload(1).get_payload(decode=True),
                                       message.get_payload(1).get_content_charset()))
        self.assertEqual("text/html", message.get_payload(1).get_content_type())
