"""
samples/create_sample_pdfs.py
──────────────────────────────
Creates the 4 sample test PDFs used in the samples/ folder.
Run once: python samples/create_sample_pdfs.py
Requires: pip install reportlab
"""
from pathlib import Path

OUTPUT_DIR = Path(__file__).parent

# Try reportlab; if not installed, print instructions
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False


def make_pdf(filename: str, title: str, pages: list[str]) -> None:
    path = OUTPUT_DIR / filename
    c = canvas.Canvas(str(path), pagesize=A4)
    width, height = A4

    for i, page_text in enumerate(pages):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, height - 50, title)
        c.setFont("Helvetica", 10)
        y = height - 90
        for line in page_text.split("\n"):
            if y < 60:
                c.showPage()
                y = height - 50
            c.drawString(50, y, line[:120])
            y -= 14
        c.showPage()

    c.save()
    print(f"Created: {path}")


def create_policy_handbook() -> None:
    pages = [
        """
MEDICOVER HEALTH INSURANCE POLICY HANDBOOK
Version 2024-01

TABLE OF CONTENTS
1. Introduction
2. Covered Benefits
3. Claim Submission Process
4. General Exclusions
5. Contact Information
        """,
        """
SECTION 1: INTRODUCTION

This policy handbook describes the terms and conditions of your MediCover
health insurance plan. Please read it carefully.

Coverage is subject to policy limits and exclusions listed in Section 4.
This policy is governed by the laws of the State of New York.
        """,
        """
SECTION 2: COVERED BENEFITS

2.1 Hospitalisation
The policy covers in-patient hospitalisation expenses including:
- Room rent up to $500 per day
- Surgeon fees up to $10,000 per procedure
- Anaesthesia charges
- ICU charges up to $1,500 per day
- Operation theatre charges

2.2 Day Care Procedures
Procedures not requiring 24-hour admission are covered if listed in
the approved day-care procedure list.

2.3 Diagnostic Tests
Laboratory tests and imaging (X-ray, MRI, CT scan) are covered when
ordered by a licensed physician in connection with a covered condition.

2.4 Emergency Care
Emergency room visits are covered when the condition requires immediate
medical attention. Non-emergency use of ER is not covered.

2.5 Maternity (Optional Rider)
Maternity benefits are available only if the optional maternity rider
has been added to the policy and a 9-month waiting period has elapsed.
        """,
        """
SECTION 3: CLAIM SUBMISSION PROCESS

3.1 Filing a Claim
Claims must be filed within 90 days of the date of service.
Submit the completed claim form along with:
- Original itemised bill from the medical provider
- Diagnosis report or discharge summary
- Doctor's prescription and referral (if applicable)

3.2 Claim Review Timeline
Standard claims are processed within 7 business days.
Complex claims requiring additional review may take up to 21 business days.

3.3 Direct Billing
For network hospitals, direct billing is available. The insured is
responsible only for the deductible and co-pay amounts.
        """,
        """
SECTION 4: GENERAL EXCLUSIONS

The following conditions and treatments are NOT covered under this policy:

1. Pre-existing conditions diagnosed or treated within 48 months
   before the policy start date
2. Cosmetic surgery, plastic surgery, or aesthetic procedures
   unless required due to accident
3. HIV/AIDS and related opportunistic infections
4. Self-inflicted injuries or attempted suicide
5. Alcoholism and substance abuse treatment
6. Dental treatment and orthodontic procedures unless resulting
   from an accident causing bodily injury
7. Pregnancy and childbirth (unless optional maternity rider is active)
8. Infertility treatment and assisted reproduction
9. Experimental treatments and clinical trials not approved by FDA
10. War injuries, terrorism-related injuries, or civil unrest
11. Aviation accidents (other than as a fare-paying passenger)
12. Nuclear hazard or radioactive contamination
13. Obesity treatment including bariatric surgery
14. Sleep disorders and related treatments
15. Congenital diseases or birth defects

IMPORTANT: This exclusions list is not exhaustive. The policy terms
and conditions document governs in case of dispute.
        """,
        """
SECTION 5: CONTACT INFORMATION

Customer Service:   1-800-MEDICOVER
Claims Department:  claims@medicover.com
Emergency Hotline:  1-888-MEDI-911
Website:            www.medicover.com

Office Hours: Monday – Friday, 8:00 AM – 6:00 PM EST
For after-hours emergencies, call the 24/7 hotline.

MediCover Insurance Company
123 Insurance Plaza
New York, NY 10001
        """,
    ]
    make_pdf("policy_handbook.pdf", "MediCover Policy Handbook", pages)


def create_bill_accepted() -> None:
    pages = [
        """
METROPOLITAN GENERAL HOSPITAL
123 Medical Center Drive, New York, NY 10001
Phone: (212) 555-0100

ITEMISED BILL

Patient Name:    John Smith
Date of Service: 2024-03-15
Diagnosis:       Acute appendicitis (K35.80)
Attending:       Dr. Sarah Johnson, MD

---------------------------------------------------------
ITEMISED CHARGES
---------------------------------------------------------
Emergency Room Visit                          $1,200.00
Laboratory Tests (CBC, Metabolic Panel)         $450.00
CT Scan - Abdomen                               $800.00
Appendectomy (Laparoscopic)                   $5,500.00
Anaesthesia                                   $1,200.00
Operating Room                                $1,800.00
Post-op Recovery Room (2 hours)                 $400.00
Hospital Room (1 night)                         $500.00
Nursing Care                                    $350.00
Medications                                     $125.00
---------------------------------------------------------
SUBTOTAL                                     $12,325.00
Insurance Discount (Network)                 -$2,465.00
---------------------------------------------------------
TOTAL BILLED TO INSURANCE                     $9,860.00
Patient Co-pay                                  $500.00
---------------------------------------------------------
AMOUNT DUE FROM PATIENT                         $500.00

This bill is for acute appendicitis, a medical emergency. Treatment
was medically necessary and performed by in-network providers.

Authorised by: Dr. Sarah Johnson, MD
Date: 2024-03-15
        """
    ]
    make_pdf("bill_accepted.pdf", "Hospital Bill - Acute Appendicitis (Expected: ACCEPTED)", pages)


def create_bill_excluded() -> None:
    pages = [
        """
COSMETIC WELLNESS CENTER
456 Beauty Blvd, Beverly Hills, CA 90210
Phone: (310) 555-0200

PATIENT INVOICE

Patient Name:    Jane Doe
Date of Service: 2024-04-10
Diagnosis:       Obesity (E66.01) - Bariatric Surgery
Attending:       Dr. Michael Green, MD

---------------------------------------------------------
ITEMISED CHARGES
---------------------------------------------------------
Pre-operative Consultation                      $350.00
Laboratory Tests                                $280.00
Gastric Bypass Surgery (Roux-en-Y)           $18,500.00
Anaesthesia                                   $2,400.00
Operating Room                                $3,200.00
Hospital Stay (3 nights)                      $1,500.00
Post-op Dietitian Consultation                  $200.00
Follow-up Visit                                 $150.00
Medications                                     $175.00
---------------------------------------------------------
TOTAL                                        $26,755.00

DIAGNOSIS DETAILS:
Patient presents with morbid obesity (BMI 42). Bariatric surgery
recommended after conservative management failed.

Authorised by: Dr. Michael Green, MD
Date: 2024-04-10
        """
    ]
    make_pdf("bill_excluded.pdf", "Hospital Bill - Bariatric Surgery (Expected: REJECTED - Excluded)", pages)


def create_bill_amount_exceeded() -> None:
    pages = [
        """
RIVERDALE MEDICAL CENTER
789 Health Ave, Chicago, IL 60601
Phone: (312) 555-0300

PATIENT INVOICE

Patient Name:    Robert Brown
Date of Service: 2024-05-20
Diagnosis:       Type 2 Diabetes follow-up
Attending:       Dr. Emily Chen, MD

---------------------------------------------------------
ITEMISED CHARGES
---------------------------------------------------------
Office Consultation                             $250.00
HbA1c Laboratory Test                            $85.00
Comprehensive Metabolic Panel                   $120.00
Ophthalmology Referral                           $200.00
Medications (90-day supply)                     $345.00
Diabetes Education Session                      $150.00
---------------------------------------------------------
TOTAL BILLED                                  $1,150.00

NOTE: Claim submitted by patient for $4,500.00 which EXCEEDS
the actual bill total of $1,150.00.

Authorised by: Dr. Emily Chen, MD
Date: 2024-05-20
        """
    ]
    make_pdf("bill_amount_exceeded.pdf", "Hospital Bill - Amount Mismatch (Expected: REJECTED)", pages)


def create_bill_mismatch() -> None:
    pages = [
        """
LAKESIDE HOSPITAL
321 Lake Shore Drive, Seattle, WA 98101
Phone: (206) 555-0400

PATIENT INVOICE

Patient Name:    Alice Johnson
Date of Service: 2024-06-01
Diagnosis:       Migraine with aura (G43.109)
Attending:       Dr. David Park, MD

---------------------------------------------------------
ITEMISED CHARGES
---------------------------------------------------------
Emergency Room Visit                            $800.00
Neurological Examination                        $350.00
MRI Brain                                     $1,200.00
Medications (Sumatriptan, Anti-emetics)         $180.00
---------------------------------------------------------
TOTAL                                         $2,530.00

NOTE: Patient's claim form states diagnosis as "cardiac chest pain"
at "Seattle General Hospital" on "2024-07-15" — which does NOT match
this bill (migraine, Lakeside Hospital, 2024-06-01).
This bill is to demonstrate the consistency check failure scenario.

Authorised by: Dr. David Park, MD
Date: 2024-06-01
        """
    ]
    make_pdf("bill_mismatch.pdf", "Hospital Bill - Consistency Mismatch (Expected: NEEDS_REVIEW)", pages)


if __name__ == "__main__":
    if not REPORTLAB_AVAILABLE:
        print("Install reportlab first:  pip install reportlab")
        raise SystemExit(1)

    create_policy_handbook()
    create_bill_accepted()
    create_bill_excluded()
    create_bill_amount_exceeded()
    create_bill_mismatch()
    print("\nAll 5 sample PDFs created in samples/")
