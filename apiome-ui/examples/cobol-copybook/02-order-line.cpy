      *****************************************************************
      * COBOL copybook example - ORDER-LINE item for a sales feed.
      *****************************************************************
       01  ORDER-LINE.
           05  ORDER-ID                  PIC 9(10).
           05  ORDER-ITEM-SKU            PIC X(12).
           05  ORDER-QUANTITY            PIC 9(4).
           05  ORDER-UNIT-PRICE          PIC S9(7)V99 COMP-3.
           05  ORDER-LINE-TOTAL          PIC S9(9)V99 COMP-3.
