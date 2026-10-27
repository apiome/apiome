      *****************************************************************
      * GETSTOCK - request and response of the getStockLevel call.
      *****************************************************************
       01  GET-STOCK-REQUEST.
           05  REQ-SKU                   PIC X(12).
       01  GET-STOCK-RESPONSE.
           05  RESP-SKU                  PIC X(12).
           05  RESP-ON-HAND              PIC 9(7).
           05  RESP-RESERVED             PIC 9(7).
