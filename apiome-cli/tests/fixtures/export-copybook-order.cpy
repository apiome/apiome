      ******************************************************************
      * Generated COBOL copybook for Order
      ******************************************************************
       01  ORDER-X.
           05  CUSTOMER-LOYALTY-PROGRAM-MEMBE PIC X(20).
           05  DISCOUNT-RATE COMP-2.
           05  LINES-X-COUNT PIC S9(4) COMP.
           05  LINES-X OCCURS 0 TO 50 TIMES DEPENDING ON LINES-X-COUNT.
      * format: int32
               10  QUANTITY PIC 9(18) COMP.
               10  SKU PIC X(16).
               10  UNIT-PRICE COMP-2.
               10  WAREHOUSE-BIN-LOCATION-REFEREN PIC X(8).
           05  NOTES-COUNT PIC S9(4) COMP.
           05  NOTES PIC X(255) OCCURS 0 TO 10 TIMES
                          DEPENDING ON NOTES-COUNT.
           05  ORDER-ID PIC X(12).
           05  SHIP-TO.
               10  CITY PIC X(30).
               10  GEO.
                   15  LATITUDE COMP-2.
                   15  LONGITUDE COMP-2.
               10  POSTAL-CODE PIC X(10).
               10  STREET PIC X(40).
           05  TOTAL COMP-2.
