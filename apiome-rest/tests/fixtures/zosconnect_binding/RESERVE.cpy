      *****************************************************************
      * RESERVE - request and response of the reserveStock call.
      *****************************************************************
       01  RESERVE-REQUEST.
           05  RES-SKU                   PIC X(12).
           05  RES-QUANTITY              PIC 9(5).
       01  RESERVE-RESPONSE.
           05  RES-RESERVATION-ID        PIC X(20).
           05  RES-STATUS                PIC X(10).
