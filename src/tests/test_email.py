import logging
import unittest

from email.header import Header, decode_header, make_header

from lazr.smtptest.controller import QueueController

from cherrypie.email import Mailer


logger = logging.getLogger(__name__)


class MailerTest(unittest.TestCase):

    def setUp(self):
        self.controller = QueueController("localhost", 9025)
        self.controller.start()

    def tearDown(self):
        self.controller.stop()

    def test_send_mail(self):
        mailer = Mailer("localhost", 9025)
        body = "This is the bloody test body"
        mailer.send_mail("rcpt@example.com", "from@example.com", "test subject", body)

        messages = list(self.controller)
        message = messages[0]
        (from_str, from_cs) = decode_header(message["From"])[0]
        (to_str, to_cs) = decode_header(message["To"])[0]
        (subject_str, subject_cs) = decode_header(message["Subject"])[0]

        self.assertEqual("from@example.com", from_str)
        self.assertEqual("rcpt@example.com", to_str)
        self.assertEqual("test subject", subject_str)
        self.assertEqual(body, message.get_payload(decode=True))