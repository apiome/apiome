      *****************************************************************
      * COBOL copybook example - a fixed-layout CUSTOMER record.
      *
      * A copybook is the data-schema form for mainframe records: the
      * level numbers (01/05/10) express nesting and PICTURE (PIC)
      * clauses give each field its type, length, and sign/decimal:
      *   X = alphanumeric, 9 = numeric, S = signed, V = implied
      *   decimal point, COMP-3 = packed decimal. OCCURS gives arrays.
      * The 01 group becomes a catalog class; each elementary item a
      * typed property. Columns 1-6 are sequence area, 7 is the
      * indicator area, code lives in columns 8-72 (fixed format).
      *****************************************************************
       01  CUSTOMER-RECORD.
           05  CUST-ID                 PIC 9(8).
           05  CUST-NAME.
               10  CUST-FIRST-NAME     PIC X(20).
               10  CUST-LAST-NAME      PIC X(20).
           05  CUST-STATUS             PIC X(1).
               88  CUST-ACTIVE         VALUE 'A'.
               88  CUST-SUSPENDED      VALUE 'S'.
               88  CUST-CLOSED         VALUE 'C'.
           05  CUST-BALANCE            PIC S9(9)V99 COMP-3.
           05  CUST-PHONE-COUNT        PIC 9(2).
           05  CUST-PHONES OCCURS 1 TO 5 TIMES
                          DEPENDING ON CUST-PHONE-COUNT.
               10  CUST-PHONE-TYPE     PIC X(1).
               10  CUST-PHONE-NUMBER   PIC X(15).
           05  CUST-CREATED-DATE       PIC 9(8).
