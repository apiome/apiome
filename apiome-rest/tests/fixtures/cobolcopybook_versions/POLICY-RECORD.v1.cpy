      *****************************************************************
      * Layout-diff fixture (MFI-21.1, #3991) - version 1 of a fixed-
      * length POLICY record, 74 bytes. FILLER keeps 20 bytes spare.
      *****************************************************************
       01  POLICY-RECORD.
           05  POL-NUMBER              PIC X(10).
           05  POL-HOLDER-NAME         PIC X(30).
           05  POL-STATUS              PIC X(1).
               88  POL-ACTIVE          VALUE 'A'.
               88  POL-LAPSED          VALUE 'L'.
           05  POL-PREMIUM             PIC S9(7)V99 COMP-3.
           05  POL-EFFECTIVE-DATE      PIC 9(8).
           05  FILLER                  PIC X(20).
