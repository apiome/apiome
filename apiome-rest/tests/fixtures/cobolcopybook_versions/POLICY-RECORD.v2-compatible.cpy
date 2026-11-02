      *****************************************************************
      * Layout-diff fixture (MFI-21.1, #3991) - version 2: compatible.
      * POL-AGENT-CODE is carved out of the spare FILLER and a third
      * status condition is added; the record is still 74 bytes and
      * every existing item keeps its offset.
      *****************************************************************
       01  POLICY-RECORD.
           05  POL-NUMBER              PIC X(10).
           05  POL-HOLDER-NAME         PIC X(30).
           05  POL-STATUS              PIC X(1).
               88  POL-ACTIVE          VALUE 'A'.
               88  POL-LAPSED          VALUE 'L'.
               88  POL-CANCELLED       VALUE 'C'.
           05  POL-PREMIUM             PIC S9(7)V99 COMP-3.
           05  POL-EFFECTIVE-DATE      PIC 9(8).
           05  POL-AGENT-CODE          PIC X(6).
           05  FILLER                  PIC X(14).
