import unittest

from procurement.license_check import audit_docx, run_license_check, verify_audit


class LicenseCheckImportTests(unittest.TestCase):
    def test_license_modules_are_importable_from_new_package(self):
        self.assertTrue(hasattr(audit_docx, "main"))
        self.assertTrue(hasattr(run_license_check, "main"))
        self.assertTrue(hasattr(verify_audit, "main"))


if __name__ == "__main__":
    unittest.main()
