"""Tracked silent-loss pairs of the export conformance matrix — X1 (#6222). GENERATED.

Each entry is a (source family, target) pair whose export reports no loss while the round trip
shows drift. The gate fails on a silent-loss pair NOT listed here, and on a listed pair that no
longer reproduces (fixed: regenerate to drop it). Drive this list to zero by making the target's
fidelity report name the loss, fixing the emitter, or refusing the pair with a reason.

Regenerate with `UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py`.
"""

from typing import Dict, Tuple

KNOWN_SILENT_LOSS: Dict[Tuple[str, str], str] = {
    # --- asn1 (1) ---
    ('nacha', 'asn1'):
        'changed root; removed type NACHA-ACH.AchFile; removed type NACHA-ACH.Batch; removed type NACHA-ACH.B',
    # --- asyncapi (10) ---
    ('asyncapi', 'asyncapi'):
        'changed channel user/deleted; changed channel user/signedup; changed operation onUserDeleted; change',
    ('cue', 'asyncapi'):
        'changed root; removed type Money; removed type Order; removed type OrderLine; removed type OrderStat',
    ('dbt', 'asyncapi'):
        'changed root; removed type customers; removed type orders',
    ('dhall', 'asyncapi'):
        'changed root; removed type Currency; removed type Money; removed type Order; removed type OrderLine;',
    ('k8s-crd', 'asyncapi'):
        'changed root; removed service cronwidgets.apps.example.io; removed type apps.example.io/v1.CronWidge',
    ('openapi', 'asyncapi'):
        'changed root; removed type UserProfile',
    ('pkl', 'asyncapi'):
        'changed root; removed type Money; removed type Order; removed type OrderLine; removed type OrderStat',
    ('pydantic', 'asyncapi'):
        'changed root; removed type NewOrder; removed type Order; removed type OrderLine; removed type OrderS',
    ('typescript-types', 'asyncapi'):
        'changed root; removed type NewOrder; removed type NewOrder_lines_item; removed type Order; removed t',
    ('zod', 'asyncapi'):
        'changed root; removed type NewOrder; removed type Order; removed type OrderLine; removed type OrderS',
    # --- avro (2) ---
    ('odcs', 'avro'):
        'changed root; added type commerce.orders; removed type orders',
    ('ros2', 'avro'):
        'changed root; changed type TypicalSensorMessage; removed type TypicalSensorMessage_Constants',
    # --- aws-apigateway (1) ---
    ('aws-apigateway', 'aws-apigateway'):
        'changed operation POST /orders',
    # --- azure-apim (1) ---
    ('azure-apim', 'azure-apim'):
        'changed root',
    # --- capnproto (3) ---
    ('arazzo', 'capnproto'):
        'added operation Checkout.addItem; added operation Checkout.createCart; added operation Checkout.pay;',
    ('flatbuffers', 'capnproto'):
        'changed root; added type Color; added type Monster; added type Vec3; added type Weapon; removed type',
    ('wadl', 'capnproto'):
        'removed operation GET /books; removed operation GET /books/{bookId}; removed operation POST /books; ',
    # --- cddl (15) ---
    ('cobolcopybook', 'cddl'):
        'changed root; added type CUSTOMER-RECORD; removed type CUSTOMER-RECORD.CUSTOMER-RECORD',
    ('edifact', 'cddl'):
        'changed root; added type DTM; removed type EDIFACT-INVOIC.DTM; removed type EDIFACT-INVOIC.IMD; remo',
    ('edix12', 'cddl'):
        'changed root; added type PO1; added type TransactionSet850; removed type X12-850.PO1; removed type X',
    ('fix', 'cddl'):
        'changed root; removed type FIX.4.4.Message8; added type Message8',
    ('flatbuffers', 'cddl'):
        'changed root; added type Color; added type Monster; added type Vec3; added type Weapon; removed type',
    ('hl7v2', 'cddl'):
        'changed root; removed type ADT-A01.MSH; removed type ADT-A01.MessageADTA01; added type MSH; added ty',
    ('idoc', 'cddl'):
        'changed root; added type E1EDK01; added type E1EDK03; added type E1EDK14; added type E1EDKA1; added ',
    ('iso20022', 'cddl'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('iso8583', 'cddl'):
        'changed root; removed type 0100.DE11; removed type 0100.DE12; removed type 0100.DE13; removed type 0',
    ('kafka-connect', 'cddl'):
        'changed root; added type Order; removed type com.example.orders.Order',
    ('nacha', 'cddl'):
        'changed root; added type AchFile; added type Batch; added type BatchControl; added type BatchHeader;',
    ('ncpdp', 'cddl'):
        'changed root; added type Address; added type Body; added type CommunicationNumbers; added type DateO',
    ('sepa', 'cddl'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('swift-mt', 'cddl'):
        'changed root; added type CodeWord; added type Field13C; added type Field20; added type Field23B; add',
    ('tradacoms', 'cddl'):
        'changed root; added type MessageORDERS; added type OLD; removed type TRADACOMS-ORDERS.MessageORDERS;',
    # --- cloudevents (8) ---
    ('json-schema', 'cloudevents'):
        'added channel com.example.product; added operation 409bca25-9ae3-4fdf-a04b-5c1f1a658aa6; changed roo',
    ('jtd', 'cloudevents'):
        'added channel com.example.user; added operation 6521d798-2692-44e5-a0c4-4aed28197872; changed root; ',
    ('k8s-crd', 'cloudevents'):
        'added channel com.example.cronwidget; added operation 28ed5236-1c29-4800-8676-2d5517be627e; changed ',
    ('odcs', 'cloudevents'):
        'added channel com.example.orders; added operation 76e4b4bb-487a-479d-af78-b3e5a1d8a191; changed root',
    ('owl', 'cloudevents'):
        'added channel com.example.commerce.ontology; added operation 7f79a76f-c45c-4d5f-9943-7431ab7d7089; c',
    ('ros2', 'cloudevents'):
        'added channel com.example.typicalsensormessage; added operation 918dfb0c-bc58-4129-96ca-57d4e5267546',
    ('sparkplug', 'cloudevents'):
        'changed channel spBv1.0/{group_id}/NBIRTH/{edge_node_id}; added operation d784c0c3-9de9-4418-b772-c8',
    ('typescript-types', 'cloudevents'):
        'added channel com.example.orderline; added operation 6337af43-2863-4988-9430-d5111c42fb4a; changed r',
    # --- connectrpc (15) ---
    ('a2a', 'connectrpc'):
        'removed agent Travel Concierge; removed operation Travel Concierge.build-itinerary; removed operatio',
    ('acp', 'connectrpc'):
        'removed agent research-assistant; removed operation research-assistant.Cite sources; removed operati',
    ('agents-manifest', 'connectrpc'):
        'added operation A2A_agents.https___returns_northwind_example__well_known_agent_card_json; added oper',
    ('apigee', 'connectrpc'):
        'removed operation GET /v2/orders/orders; removed operation GET /v2/orders/orders/{segment1}; removed',
    ('arazzo', 'connectrpc'):
        'removed operation checkout#addItem; removed operation checkout#createCart; removed operation checkou',
    ('azure-apim', 'connectrpc'):
        'removed operation GET /orders; removed operation GET /orders/{orderId}; added operation default.get_',
    ('consul', 'connectrpc'):
        'removed operation ANY /v2/orders; added operation orders.ANY__v2_orders; changed root; changed servi',
    ('envoy-xds', 'connectrpc'):
        'removed operation ANY /; removed operation ANY /health; removed operation ANY /v2/orders; removed op',
    ('gateway-api', 'connectrpc'):
        'removed operation GET /users; removed operation GET /users/{userId}; removed operation POST /users; ',
    ('haproxy', 'connectrpc'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /metrics; removed ope',
    ('istio', 'connectrpc'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /v2/products; removed',
    ('kong', 'connectrpc'):
        'removed operation DELETE /users/{userId}; removed operation GET /users; removed operation GET /users',
    ('nginx', 'connectrpc'):
        'removed operation ANY /; removed operation ANY /#api.example.com:80@return; removed operation ANY /h',
    ('traefik', 'connectrpc'):
        'removed operation ANY /; removed operation ANY /v2/orders; removed operation ANY /v2/products; added',
    ('tyk', 'connectrpc'):
        'removed operation DELETE /v2/orders/orders/{id}; removed operation GET /v2/orders/orders; removed op',
    # --- corbaidl (5) ---
    ('arazzo', 'corbaidl'):
        'added operation Storefront_checkout.checkout.addItem; added operation Storefront_checkout.checkout.c',
    ('capnproto', 'corbaidl'):
        'removed operation Directory.add; removed operation Directory.lookup; added operation DirectoryModule',
    ('flatbuffers', 'corbaidl'):
        'changed root; changed type example.game.Color; changed type example.game.Monster; changed type examp',
    ('wsdl', 'corbaidl'):
        'added operation example.com.orders.OrderPort.CancelOrder; added operation example.com.orders.OrderPo',
    ('wsdl2', 'corbaidl'):
        'added operation example.com.orders.OrderInterface.cancelOrder; added operation example.com.orders.Or',
    # --- fhir (49) ---
    ('a2a', 'fhir'):
        'removed agent Travel Concierge; added operation GET /Travel Concierge; added operation GET /Travel C',
    ('acp', 'fhir'):
        'removed agent research-assistant; added operation GET /research-assistant; added operation GET /rese',
    ('agents-manifest', 'fhir'):
        'added operation GET /A2A agents; added operation GET /A2A agents/{id}; added operation POST /A2A age',
    ('api-blueprint', 'fhir'):
        'added operation GET /NewTask; added operation GET /NewTask/{id}; removed operation GET /tasks; remov',
    ('apigee', 'fhir'):
        'added operation GET /default; added operation GET /default/{id}; removed operation GET /v2/orders/or',
    ('arazzo', 'fhir'):
        'added operation GET /checkout; added operation GET /checkout/{id}; added operation POST /checkout; r',
    ('avro-idl', 'fhir'):
        'added operation GET /Order; added operation GET /Order/{id}; added operation POST /Order; removed op',
    ('azure-apim', 'fhir'):
        'added operation GET /default; added operation GET /default/{id}; removed operation GET /orders; remo',
    ('capnproto', 'fhir'):
        'removed operation Directory.add; removed operation Directory.lookup; added operation GET /AddressBoo',
    ('cobolcopybook', 'fhir'):
        'added operation GET /CUSTOMER-RECORD; added operation GET /CUSTOMER-RECORD/{id}; added operation POS',
    ('connectrpc', 'fhir'):
        'added operation GET /CompleteTaskRequest; added operation GET /CompleteTaskRequest/{id}; added opera',
    ('consul', 'fhir'):
        'removed operation ANY /v2/orders; added operation GET /orders; added operation GET /orders/{id}; add',
    ('corbaidl', 'fhir'):
        'removed operation Banking.Bank.deposit; removed operation Banking.Bank.getAccount; removed operation',
    ('edifact', 'fhir'):
        'added operation GET /DTM; added operation GET /DTM/{id}; added operation POST /DTM; changed root; ad',
    ('edix12', 'fhir'):
        'added operation GET /PO1; added operation GET /PO1/{id}; added operation POST /PO1; changed root; ad',
    ('envoy-xds', 'fhir'):
        'removed operation ANY /; removed operation ANY /health; removed operation ANY /v2/orders; removed op',
    ('fix', 'fhir'):
        'added operation GET /Message8; added operation GET /Message8/{id}; added operation POST /Message8; c',
    ('flatbuffers', 'fhir'):
        'added operation GET /Color; added operation GET /Color/{id}; added operation POST /Color; changed ro',
    ('gateway-api', 'fhir'):
        'added operation GET /identity/users; added operation GET /identity/users/{id}; removed operation GET',
    ('haproxy', 'fhir'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /metrics; removed ope',
    ('hl7v2', 'fhir'):
        'added operation GET /MSH; added operation GET /MSH/{id}; added operation POST /MSH; changed root; ad',
    ('idoc', 'fhir'):
        'added operation GET /E1EDK01; added operation GET /E1EDK01/{id}; added operation POST /E1EDK01; chan',
    ('iso20022', 'fhir'):
        'added operation GET /Amt; added operation GET /Amt/{id}; added operation POST /Amt; changed root; ad',
    ('iso8583', 'fhir'):
        'added operation GET /DE11; added operation GET /DE11/{id}; added operation POST /DE11; changed root;',
    ('istio', 'fhir'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /v2/products; added o',
    ('kafka-connect', 'fhir'):
        'added operation GET /Order; added operation GET /Order/{id}; added operation POST /Order; changed ro',
    ('kong', 'fhir'):
        'removed operation DELETE /users/{userId}; removed operation GET /users; added operation GET /users-s',
    ('lwm2m', 'fhir'):
        'added operation GET /Temperature; added operation GET /Temperature/{id}; added operation POST /Tempe',
    ('matter', 'fhir'):
        'added operation GET /OnOff; added operation GET /OnOff/{id}; removed operation OnOffService.Off; rem',
    ('nacha', 'fhir'):
        'added operation GET /AchFile; added operation GET /AchFile/{id}; added operation POST /AchFile; chan',
    ('ncpdp', 'fhir'):
        'added operation GET /Address; added operation GET /Address/{id}; added operation POST /Address; chan',
    ('nginx', 'fhir'):
        'removed operation ANY /; removed operation ANY /#api.example.com:80@return; removed operation ANY /h',
    ('odata', 'fhir'):
        'added operation GET /Address; added operation GET /Address/{id}; removed operation GET /Orders; remo',
    ('odata-v2', 'fhir'):
        'added operation GET /Customer; added operation GET /Customer/{id}; removed operation GET /Customers;',
    ('protobuf', 'fhir'):
        'added operation GET /CreateProductRequest; added operation GET /CreateProductRequest/{id}; added ope',
    ('protobuf-editions', 'fhir'):
        'added operation GET /GetOrderRequest; added operation GET /GetOrderRequest/{id}; added operation POS',
    ('raml', 'fhir'):
        'added operation GET /Book; added operation GET /Book/{id}; removed operation GET /books; removed ope',
    ('sepa', 'fhir'):
        'added operation GET /Amt; added operation GET /Amt/{id}; added operation POST /Amt; changed root; ad',
    ('swift-mt', 'fhir'):
        'added operation GET /CodeWord; added operation GET /CodeWord/{id}; added operation POST /CodeWord; c',
    ('thrift', 'fhir'):
        'added operation GET /CreateUserRequest; added operation GET /CreateUserRequest/{id}; added operation',
    ('tradacoms', 'fhir'):
        'added operation GET /MessageORDERS; added operation GET /MessageORDERS/{id}; added operation POST /M',
    ('traefik', 'fhir'):
        'removed operation ANY /; removed operation ANY /v2/orders; removed operation ANY /v2/products; added',
    ('tyk', 'fhir'):
        'removed operation DELETE /v2/orders/orders/{id}; added operation GET /Orders API; added operation GE',
    ('typespec', 'fhir'):
        'added operation GET /NewPet; added operation GET /NewPet/{id}; removed operation GET /pets; removed ',
    ('wadl', 'fhir'):
        'added operation GET /Book; added operation GET /Book/{id}; removed operation GET /books; removed ope',
    ('wsdl', 'fhir'):
        'added operation GET /CancelOrderRequest; added operation GET /CancelOrderRequest/{id}; added operati',
    ('wsdl2', 'fhir'):
        'added operation GET /cancelOrder; added operation GET /cancelOrder/{id}; added operation POST /cance',
    ('xmlrpc', 'fhir'):
        'added operation GET /InventoryReserveStockParam3; added operation GET /InventoryReserveStockParam3/{',
    ('zosconnect', 'fhir'):
        'added operation GET /GET-STOCK-REQUEST; added operation GET /GET-STOCK-REQUEST/{id}; removed operati',
    # --- graphql (11) ---
    ('agents-manifest', 'graphql'):
        'added operation Mutation.https___returns_northwind_example__well_known_agent_card_json; added operat',
    ('arazzo', 'graphql'):
        'added operation Query._; removed operation checkout#addItem; removed operation checkout#createCart; ',
    ('graphql', 'graphql'):
        'removed type Dimensions',
    ('json-schema', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type Product',
    ('jtd', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type User; removed type UserAddr',
    ('k8s-crd', 'graphql'):
        'added operation Query._; changed root; added service Query; removed service cronwidgets.apps.example',
    ('odcs', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type orders',
    ('owl', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type Agent; removed type Custome',
    ('ros2', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type TypicalSensorMessage; remov',
    ('smithy', 'graphql'):
        'added operation Mutation.GetCurrentConditions; added operation Mutation.GetForecast; added operation',
    ('typescript-types', 'graphql'):
        'added operation Query._; changed root; added service Query; removed type NewOrder; removed type NewO',
    # --- json-schema (15) ---
    ('cobolcopybook', 'json-schema'):
        'changed root; added type CUSTOMER-RECORD; removed type CUSTOMER-RECORD.CUSTOMER-RECORD',
    ('edifact', 'json-schema'):
        'changed root; added type DTM; added type EDIFACT INVOIC; removed type EDIFACT-INVOIC.DTM; removed ty',
    ('edix12', 'json-schema'):
        'changed root; added type PO1; added type TransactionSet850; added type X12 850; removed type X12-850',
    ('fix', 'json-schema'):
        'changed root; added type ExecutionReport (FIX.4.4); removed type FIX.4.4.Message8',
    ('flatbuffers', 'json-schema'):
        'changed root; added type Color; added type Monster; added type Vec3; added type Weapon; added type e',
    ('hl7v2', 'json-schema'):
        'changed root; removed type ADT-A01.MSH; removed type ADT-A01.MessageADTA01; added type ADT^A01; adde',
    ('idoc', 'json-schema'):
        'changed root; added type E1EDK01; added type E1EDK03; added type E1EDK14; added type E1EDKA1; added ',
    ('iso20022', 'json-schema'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('iso8583', 'json-schema'):
        'changed root; removed type 0100.DE11; removed type 0100.DE12; removed type 0100.DE13; removed type 0',
    ('kafka-connect', 'json-schema'):
        'changed root; added type Order; removed type com.example.orders.Order',
    ('nacha', 'json-schema'):
        'changed root; added type AchFile; added type Batch; added type BatchControl; added type BatchHeader;',
    ('ncpdp', 'json-schema'):
        'changed root; added type Address; added type Body; added type CommunicationNumbers; added type DateO',
    ('sepa', 'json-schema'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('swift-mt', 'json-schema'):
        'changed root; added type CodeWord; added type Field13C; added type Field20; added type Field23B; add',
    ('tradacoms', 'json-schema'):
        'changed root; added type MessageORDERS; added type OLD; added type TRADACOMS ORDERS; removed type TR',
    # --- jtd (15) ---
    ('cobolcopybook', 'jtd'):
        'changed root; added type CUSTOMER-RECORD; removed type CUSTOMER-RECORD.CUSTOMER-RECORD',
    ('edifact', 'jtd'):
        'changed root; added type DTM; added type EDIFACT INVOIC; removed type EDIFACT-INVOIC.DTM; removed ty',
    ('edix12', 'jtd'):
        'changed root; added type PO1; added type TransactionSet850; added type X12 850; removed type X12-850',
    ('fix', 'jtd'):
        'changed root; added type ExecutionReport (FIX.4.4); removed type FIX.4.4.Message8; added type Messag',
    ('flatbuffers', 'jtd'):
        'changed root; added type Color; added type Monster; added type Vec3; added type Weapon; removed type',
    ('hl7v2', 'jtd'):
        'changed root; removed type ADT-A01.MSH; removed type ADT-A01.MessageADTA01; added type ADT^A01; adde',
    ('idoc', 'jtd'):
        'changed root; added type E1EDK01; added type E1EDK03; added type E1EDK14; added type E1EDKA1; added ',
    ('iso20022', 'jtd'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('iso8583', 'jtd'):
        'changed root; removed type 0100.DE11; removed type 0100.DE12; removed type 0100.DE13; removed type 0',
    ('kafka-connect', 'jtd'):
        'changed root; added type Order; removed type com.example.orders.Order',
    ('nacha', 'jtd'):
        'changed root; added type AchFile; added type Batch; added type BatchControl; added type BatchHeader;',
    ('ncpdp', 'jtd'):
        'changed root; added type Address; added type Body; added type CommunicationNumbers; added type DateO',
    ('sepa', 'jtd'):
        'changed root; added type Amt; added type CdtTrfTxInf; added type Cdtr; added type CdtrAcct; added ty',
    ('swift-mt', 'jtd'):
        'changed root; added type CodeWord; added type Field13C; added type Field20; added type Field23B; add',
    ('tradacoms', 'jtd'):
        'changed root; added type MessageORDERS; added type OLD; added type TRADACOMS ORDERS; removed type TR',
    # --- k8s-crd (15) ---
    ('cue', 'k8s-crd'):
        'changed root; added service moneys.example.com; removed type Money; removed type Order; removed type',
    ('dbt', 'k8s-crd'):
        'changed root; added service customerses.example.com; removed type customers; added type example.com/',
    ('dhall', 'k8s-crd'):
        'changed root; added service moneys.example.com; removed type Currency; removed type Money; removed t',
    ('json-schema', 'k8s-crd'):
        'changed root; added service products.example.com; removed type Product; added type example.com/v1.Pr',
    ('jtd', 'k8s-crd'):
        'changed root; added service users.example.com; removed type User; removed type UserAddress; removed ',
    ('odcs', 'k8s-crd'):
        'changed root; added service orderses.commerce; added type commerce/v1.Orders; removed type orders',
    ('openapi', 'k8s-crd'):
        'changed root; added service userprofiles.example.com; removed type UserProfile; added type example.c',
    ('owl', 'k8s-crd'):
        'changed root; added service agents.example.com; removed type Agent; removed type Customer; removed t',
    ('pkl', 'k8s-crd'):
        'changed root; added service orderses.example.com; removed type Money; removed type Order; removed ty',
    ('pydantic', 'k8s-crd'):
        'changed root; added service orderlines.example.com; removed type NewOrder; removed type Order; remov',
    ('ros2', 'k8s-crd'):
        'changed root; added service typicalsensormessages.example.com; removed type TypicalSensorMessage; re',
    ('shacl', 'k8s-crd'):
        'changed root; added service organisationshapes.example.com; removed type OrganisationShape; removed ',
    ('sql-ddl', 'k8s-crd'):
        'changed root; added service customers.example.com; removed type commerce.customer; removed type comm',
    ('typescript-types', 'k8s-crd'):
        'changed root; added service orderlines.example.com; removed type NewOrder; removed type NewOrder_lin',
    ('zod', 'k8s-crd'):
        'changed root; added service orderlines.example.com; removed type NewOrder; removed type Order; remov',
    # --- kafka-connect (3) ---
    ('json-schema', 'kafka-connect'):
        'changed root; changed type Product',
    ('k8s-crd', 'kafka-connect'):
        'changed root; removed service cronwidgets.apps.example.io; added type apps.example.io.CronWidget; re',
    ('odcs', 'kafka-connect'):
        'changed root; added type commerce.orders; removed type orders',
    # --- odata (49) ---
    ('a2a', 'odata'):
        'removed agent Travel Concierge; added operation GET /Travel Concierge; added operation GET /Travel C',
    ('acp', 'odata'):
        'removed agent research-assistant; added operation GET /research-assistant; added operation GET /rese',
    ('agents-manifest', 'odata'):
        'added operation GET /A2A agents; added operation GET /A2A agents({key}); added operation GET /Agent ',
    ('api-blueprint', 'odata'):
        'added operation GET /Task API; added operation GET /Task API({key}); removed operation GET /tasks; r',
    ('apigee', 'odata'):
        'added operation GET /default; added operation GET /default({key}); removed operation GET /v2/orders/',
    ('arazzo', 'odata'):
        'added operation GET /checkout; added operation GET /checkout({key}); added operation POST /checkout;',
    ('avro-idl', 'odata'):
        'added operation GET /OrderService; added operation GET /OrderService({key}); added operation POST /O',
    ('azure-apim', 'odata'):
        'added operation GET /default; added operation GET /default({key}); removed operation GET /orders; re',
    ('capnproto', 'odata'):
        'removed operation Directory.add; removed operation Directory.lookup; added operation GET /Directory;',
    ('cobolcopybook', 'odata'):
        'changed root; changed type CUSTOMER-RECORD.CUSTOMER-RECORD',
    ('connectrpc', 'odata'):
        'added operation GET /TaskService; added operation GET /TaskService({key}); added operation POST /Tas',
    ('consul', 'odata'):
        'removed operation ANY /v2/orders; added operation GET /orders; added operation GET /orders({key}); a',
    ('corbaidl', 'odata'):
        'removed operation Banking.Bank.deposit; removed operation Banking.Bank.getAccount; removed operation',
    ('edifact', 'odata'):
        'changed root; changed type EDIFACT-INVOIC.DTM; changed type EDIFACT-INVOIC.IMD; changed type EDIFACT',
    ('edix12', 'odata'):
        'changed root; changed type X12-850.PO1; changed type X12-850.TransactionSet850',
    ('envoy-xds', 'odata'):
        'removed operation ANY /; removed operation ANY /health; removed operation ANY /v2/orders; removed op',
    ('fhir', 'odata'):
        'changed operation GET /Patient; added operation GET /Patient({key}); removed operation GET /Patient/',
    ('fix', 'odata'):
        'changed root; changed type FIX.4.4.Message8',
    ('flatbuffers', 'odata'):
        'changed root; changed type example.game.Color; changed type example.game.Monster; changed type examp',
    ('gateway-api', 'odata'):
        'added operation GET /identity/users; added operation GET /identity/users({key}); removed operation G',
    ('haproxy', 'odata'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /metrics; removed ope',
    ('hl7v2', 'odata'):
        'changed root; changed type ADT-A01.MSH; changed type ADT-A01.MessageADTA01',
    ('idoc', 'odata'):
        'changed root; changed type IDOC-ORDERS05.E1EDK01; changed type IDOC-ORDERS05.E1EDK03; changed type I',
    ('iso20022', 'odata'):
        'changed root; changed type pain.001.001.09.Amt; changed type pain.001.001.09.CdtTrfTxInf; changed ty',
    ('iso8583', 'odata'):
        'changed root; changed type 0100.DE11; changed type 0100.DE12; changed type 0100.DE13; changed type 0',
    ('istio', 'odata'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /v2/products; added o',
    ('kafka-connect', 'odata'):
        'changed root; changed type com.example.orders.Order',
    ('kong', 'odata'):
        'removed operation DELETE /users/{userId}; removed operation GET /users; added operation GET /users-s',
    ('lwm2m', 'odata'):
        'added operation GET /TemperatureService; added operation GET /TemperatureService({key}); added opera',
    ('matter', 'odata'):
        'added operation GET /OnOffService; added operation GET /OnOffService({key}); removed operation OnOff',
    ('nacha', 'odata'):
        'changed root; changed type NACHA-ACH.AchFile; changed type NACHA-ACH.Batch; changed type NACHA-ACH.B',
    ('ncpdp', 'odata'):
        'changed root; changed type NCPDP-SCRIPT.Address; changed type NCPDP-SCRIPT.Body; changed type NCPDP-',
    ('nginx', 'odata'):
        'removed operation ANY /; removed operation ANY /#api.example.com:80@return; removed operation ANY /h',
    ('odata-v2', 'odata'):
        'changed root; changed type Northbound.Orders.Customer; changed type Northbound.Orders.Item; changed ',
    ('protobuf', 'odata'):
        'added operation GET /ProductService; added operation GET /ProductService({key}); added operation POS',
    ('protobuf-editions', 'odata'):
        'added operation GET /OrderService; added operation GET /OrderService({key}); added operation POST /O',
    ('raml', 'odata'):
        'added operation GET /Bookstore API; added operation GET /Bookstore API({key}); removed operation GET',
    ('sepa', 'odata'):
        'changed root; changed type pain.001.001.09.Amt; changed type pain.001.001.09.CdtTrfTxInf; changed ty',
    ('swift-mt', 'odata'):
        'changed root; changed type SWIFT-MT103.CodeWord; changed type SWIFT-MT103.Field13C; changed type SWI',
    ('thrift', 'odata'):
        'added operation GET /UserService; added operation GET /UserService({key}); added operation POST /Use',
    ('tradacoms', 'odata'):
        'changed root; changed type TRADACOMS-ORDERS.MessageORDERS; changed type TRADACOMS-ORDERS.OLD',
    ('traefik', 'odata'):
        'removed operation ANY /; removed operation ANY /v2/orders; removed operation ANY /v2/products; added',
    ('tyk', 'odata'):
        'removed operation DELETE /v2/orders/orders/{id}; added operation GET /Orders API; added operation GE',
    ('typespec', 'odata'):
        'added operation GET /Pets; added operation GET /Pets({key}); removed operation GET /pets; removed op',
    ('wadl', 'odata'):
        'added operation GET /WADL API; added operation GET /WADL API({key}); removed operation GET /books; r',
    ('wsdl', 'odata'):
        'added operation GET /OrderPort; added operation GET /OrderPort({key}); added operation POST /OrderPo',
    ('wsdl2', 'odata'):
        'added operation GET /OrderInterface; added operation GET /OrderInterface({key}); added operation POS',
    ('xmlrpc', 'odata'):
        'added operation GET /inventory.reserveStock; added operation GET /inventory.reserveStock({key}); add',
    ('zosconnect', 'odata'):
        'added operation GET /InventoryRequester; added operation GET /InventoryRequester({key}); removed ope',
    # --- oncrpc (4) ---
    ('arazzo', 'oncrpc'):
        'removed operation checkout#addItem; removed operation checkout#createCart; removed operation checkou',
    ('capnproto', 'oncrpc'):
        'added operation Directory.Directory.add; added operation Directory.Directory.lookup; removed operati',
    ('wsdl', 'oncrpc'):
        'added operation OrderPort.OrderPort.CancelOrder; added operation OrderPort.OrderPort.CreateOrder; ad',
    ('wsdl2', 'oncrpc'):
        'added operation OrderInterface.OrderInterface.cancelOrder; added operation OrderInterface.OrderInter',
    # --- openapi (51) ---
    ('acp', 'openapi'):
        'removed agent research-assistant; added operation POST /research-assistant.Cite_sources; added opera',
    ('agents-manifest', 'openapi'):
        'added operation POST /a2a.https://returns.northwind.example/.well-known/agent-card.json; added opera',
    ('apigee', 'openapi'):
        'changed operation GET /v2/orders/orders; changed operation GET /v2/orders/orders/{segment1}; changed',
    ('arazzo', 'openapi'):
        'added operation POST /checkout#addItem; added operation POST /checkout#createCart; added operation P',
    ('aws-apigateway', 'openapi'):
        'changed operation GET /orders; changed operation GET /orders/{orderId}; changed operation OPTIONS /o',
    ('azure-apim', 'openapi'):
        'changed operation GET /orders; changed operation GET /orders/{orderId}; changed root',
    ('bruno', 'openapi'):
        'changed operation POST /v2/orders; changed root; removed service Bruno collection; added service def',
    ('consul', 'openapi'):
        'removed operation ANY /v2/orders; changed root; removed service orders',
    ('cue', 'openapi'):
        'changed root; changed type Order; changed type OrderLine; changed type OrderStatus',
    ('dbt', 'openapi'):
        'changed root; changed type customers; changed type orders',
    ('dhall', 'openapi'):
        'changed root; changed type Currency; changed type Order; changed type OrderLine; changed type OrderS',
    ('discovery', 'openapi'):
        'changed operation GET /bookstore/v1/books; changed operation GET /bookstore/v1/books/{bookId}; chang',
    ('envoy-xds', 'openapi'):
        'removed operation ANY /; removed operation ANY /health; removed operation ANY /v2/orders; removed op',
    ('gateway-api', 'openapi'):
        'changed operation GET /users; changed operation GET /users/{userId}; changed operation POST /users; ',
    ('graphql', 'openapi'):
        'added operation GET /graphql/product; added operation GET /graphql/products; removed operation Query',
    ('haproxy', 'openapi'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /metrics; removed ope',
    ('har', 'openapi'):
        'changed operation DELETE /v1/users/{id}; changed operation GET /v1/users; changed operation GET /v1/',
    ('hoppscotch', 'openapi'):
        'changed operation DELETE /v2/orders/{orderId}; changed operation GET /v2/orders; changed operation G',
    ('http-file', 'openapi'):
        'changed operation GET /users; changed operation POST /users; changed root; added service default; re',
    ('insomnia', 'openapi'):
        'changed operation DELETE /v1/users/{userId}; changed operation GET /health; changed operation GET /v',
    ('istio', 'openapi'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /v2/products; changed',
    ('json-schema', 'openapi'):
        'changed root; changed type Product',
    ('jsonld', 'openapi'):
        'changed root; changed type Address; changed type LanguageMap; changed type TypicalContext',
    ('jtd', 'openapi'):
        'changed root; changed type User; changed type UserAddress',
    ('k8s-crd', 'openapi'):
        'changed root; removed service cronwidgets.apps.example.io; changed type apps.example.io/v1.CronWidge',
    ('kong', 'openapi'):
        'changed operation DELETE /users/{userId}; changed operation GET /users; changed operation GET /users',
    ('llm-tools', 'openapi'):
        'removed operation 02-typical-anthropic.create_ticket; removed operation 02-typical-anthropic.search_',
    ('mcp', 'openapi'):
        'removed operation Acme Support Tickets.prompts.summarize_ticket; removed operation Acme Support Tick',
    ('nginx', 'openapi'):
        'removed operation ANY /; removed operation ANY /#api.example.com:80@return; removed operation ANY /h',
    ('odcs', 'openapi'):
        'changed root; changed type orders',
    ('opcua-nodeset', 'openapi'):
        'removed operation MachineType.Start; added operation POST /MachineType/Start; changed root; removed ',
    ('openrpc', 'openapi'):
        'added operation POST /Wallet API/getBalance; added operation POST /Wallet API/transfer; removed oper',
    ('owl', 'openapi'):
        'changed root; changed type Agent; changed type Customer; changed type Order; changed type OrderLine;',
    ('pkl', 'openapi'):
        'changed root; changed type Order; changed type OrderLine; changed type OrderStatus; changed type Sku',
    ('postman', 'openapi'):
        'changed operation GET /tasks; changed operation GET /tasks/{id}; changed operation POST /tasks; chan',
    ('postman-v2', 'openapi'):
        'changed operation DELETE /orders/{orderId}; changed operation GET /orders; changed operation GET /or',
    ('pydantic', 'openapi'):
        'changed root; changed type NewOrder; changed type Order; changed type OrderLine; changed type OrderS',
    ('ros2', 'openapi'):
        'changed root; changed type TypicalSensorMessage; changed type TypicalSensorMessage_Constants',
    ('shacl', 'openapi'):
        'changed root; changed type OrganisationShape; changed type PersonShape',
    ('smithy', 'openapi'):
        'added operation POST /example.weather.WeatherService/GetCurrentConditions; added operation POST /exa',
    ('soapui', 'openapi'):
        'changed operation DELETE /v2/orders/{orderId}; changed operation GET /v2/orders; changed operation G',
    ('sql-ddl', 'openapi'):
        'changed root; changed type commerce.customer; changed type commerce.open_orders; changed type commer',
    ('swagger', 'openapi'):
        'changed root; changed service pet',
    ('swagger-1.2', 'openapi'):
        'changed root',
    ('thunder-client', 'openapi'):
        'changed operation GET /healthz; changed operation GET /v2/orders; changed operation GET /v2/orders/{',
    ('traefik', 'openapi'):
        'removed operation ANY /; removed operation ANY /v2/orders; removed operation ANY /v2/products; chang',
    ('trpc', 'openapi'):
        'added operation POST /orderRouter/byId; added operation POST /orderRouter/cancel; added operation PO',
    ('tyk', 'openapi'):
        'changed operation DELETE /v2/orders/orders/{id}; changed operation GET /v2/orders/orders; changed op',
    ('typescript-types', 'openapi'):
        'changed root; changed type NewOrder; changed type NewOrder_lines_item; changed type Order; changed t',
    ('wit', 'openapi'):
        'added operation POST /examples:calculator.calculate/describe; added operation POST /examples:calcula',
    ('zod', 'openapi'):
        'changed root; changed type NewOrder; changed type Order; changed type OrderLine; changed type OrderS',
    # --- openrpc (31) ---
    ('a2a', 'openrpc'):
        'removed agent Travel Concierge; added operation Travel Concierge.Build itinerary; added operation Tr',
    ('acp', 'openrpc'):
        'removed agent research-assistant; changed operation research-assistant.Cite sources; changed operati',
    ('agents-manifest', 'openrpc'):
        'added operation Northwind Store.https://returns.northwind.example/.well-known/agent-card.json; added',
    ('arazzo', 'openrpc'):
        'added operation Storefront checkout.addItem; added operation Storefront checkout.createCart; added o',
    ('avro-idl', 'openrpc'):
        'added operation OrderService.cancelOrder; added operation OrderService.getOrder; added operation Ord',
    ('capnproto', 'openrpc'):
        'changed operation Directory.add; changed operation Directory.lookup; changed root; changed type Addr',
    ('cobolcopybook', 'openrpc'):
        'changed root; added service CUSTOMER-RECORD; added type CUSTOMER-RECORD; removed type CUSTOMER-RECOR',
    ('connectrpc', 'openrpc'):
        'added operation tasks.v1.CompleteTask; added operation tasks.v1.CreateTask; added operation tasks.v1',
    ('corbaidl', 'openrpc'):
        'removed operation Banking.Bank.deposit; removed operation Banking.Bank.getAccount; removed operation',
    ('edifact', 'openrpc'):
        'changed root; added service EDIFACT INVOIC; added type DTM; removed type EDIFACT-INVOIC.DTM; removed',
    ('edix12', 'openrpc'):
        'changed root; added service X12 850; added type PO1; added type TransactionSet850; removed type X12-',
    ('fix', 'openrpc'):
        'changed root; added service ExecutionReport (FIX.4.4); removed type FIX.4.4.Message8; added type Mes',
    ('flatbuffers', 'openrpc'):
        'changed root; added service example.game; added type Color; added type Monster; added type Vec3; add',
    ('hl7v2', 'openrpc'):
        'changed root; added service ADT^A01; removed type ADT-A01.MSH; removed type ADT-A01.MessageADTA01; a',
    ('idoc', 'openrpc'):
        'changed root; added service IDoc ORDERS05; added type E1EDK01; added type E1EDK03; added type E1EDK1',
    ('iso20022', 'openrpc'):
        'changed root; added service CstmrCdtTrfInitn (pain.001.001.09); added type Amt; added type CdtTrfTxI',
    ('iso8583', 'openrpc'):
        'changed root; added service Authorization Request; removed type 0100.DE11; removed type 0100.DE12; r',
    ('kafka-connect', 'openrpc'):
        'changed root; added service Order; added type Order; removed type com.example.orders.Order',
    ('lwm2m', 'openrpc'):
        'added operation Temperature.ResetMinAndMaxMeasuredValues; removed operation TemperatureService.Reset',
    ('matter', 'openrpc'):
        'added operation On/Off.Off; added operation On/Off.OffWithEffect; added operation On/Off.On; added o',
    ('nacha', 'openrpc'):
        'changed root; added service NACHA ACH file (PPD); added type AchFile; added type Batch; added type B',
    ('ncpdp', 'openrpc'):
        'changed root; added service NCPDP SCRIPT NewRx; added type Address; added type Body; added type Comm',
    ('protobuf', 'openrpc'):
        'added operation example.catalog.v1.CreateProduct; added operation example.catalog.v1.GetProduct; add',
    ('protobuf-editions', 'openrpc'):
        'added operation example.orders.v1.GetOrder; removed operation example.orders.v1.OrderService.GetOrde',
    ('sepa', 'openrpc'):
        'changed root; added service CstmrCdtTrfInitn (pain.001.001.09); added type Amt; added type CdtTrfTxI',
    ('swift-mt', 'openrpc'):
        'changed root; added service SWIFT MT103; added type CodeWord; added type Field13C; added type Field2',
    ('thrift', 'openrpc'):
        'removed operation com.example.user.UserService.createUser; removed operation com.example.user.UserSe',
    ('tradacoms', 'openrpc'):
        'changed root; added service TRADACOMS ORDERS; added type MessageORDERS; added type OLD; removed type',
    ('wsdl', 'openrpc'):
        'added operation OrderService.CancelOrder; added operation OrderService.CreateOrder; added operation ',
    ('wsdl2', 'openrpc'):
        'added operation OrderService.cancelOrder; added operation OrderService.getOrder; added operation Ord',
    ('xmlrpc', 'openrpc'):
        'changed operation inventory.reserveStock.inventory.reserveStock; changed root; changed type Inventor',
    # --- protobuf (15) ---
    ('a2a', 'protobuf'):
        'removed agent Travel Concierge; removed operation Travel Concierge.build-itinerary; removed operatio',
    ('acp', 'protobuf'):
        'removed agent research-assistant; removed operation research-assistant.Cite sources; removed operati',
    ('agents-manifest', 'protobuf'):
        'added operation A2A_agents.https___returns_northwind_example__well_known_agent_card_json; added oper',
    ('apigee', 'protobuf'):
        'removed operation GET /v2/orders/orders; removed operation GET /v2/orders/orders/{segment1}; removed',
    ('arazzo', 'protobuf'):
        'removed operation checkout#addItem; removed operation checkout#createCart; removed operation checkou',
    ('azure-apim', 'protobuf'):
        'removed operation GET /orders; removed operation GET /orders/{orderId}; added operation default.get_',
    ('consul', 'protobuf'):
        'removed operation ANY /v2/orders; added operation orders.ANY__v2_orders; changed root; changed servi',
    ('envoy-xds', 'protobuf'):
        'removed operation ANY /; removed operation ANY /health; removed operation ANY /v2/orders; removed op',
    ('gateway-api', 'protobuf'):
        'removed operation GET /users; removed operation GET /users/{userId}; removed operation POST /users; ',
    ('haproxy', 'protobuf'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /metrics; removed ope',
    ('istio', 'protobuf'):
        'removed operation ANY /; removed operation ANY /healthz; removed operation ANY /v2/products; removed',
    ('kong', 'protobuf'):
        'removed operation DELETE /users/{userId}; removed operation GET /users; removed operation GET /users',
    ('nginx', 'protobuf'):
        'removed operation ANY /; removed operation ANY /#api.example.com:80@return; removed operation ANY /h',
    ('traefik', 'protobuf'):
        'removed operation ANY /; removed operation ANY /v2/orders; removed operation ANY /v2/products; added',
    ('tyk', 'protobuf'):
        'removed operation DELETE /v2/orders/orders/{id}; removed operation GET /v2/orders/orders; removed op',
    # --- thrift (21) ---
    ('arazzo', 'thrift'):
        'removed operation checkout#addItem; removed operation checkout#createCart; removed operation checkou',
    ('avro-idl', 'thrift'):
        'changed operation com.example.orders.OrderService.cancelOrder; changed operation com.example.orders.',
    ('capnproto', 'thrift'):
        'changed operation Directory.add; changed operation Directory.lookup; changed root; changed type Addr',
    ('connectrpc', 'thrift'):
        'changed operation tasks.v1.TaskService.CompleteTask; changed operation tasks.v1.TaskService.CreateTa',
    ('corbaidl', 'thrift'):
        'changed operation Banking.Bank.deposit; changed operation Banking.Bank.getAccount; changed operation',
    ('edix12', 'thrift'):
        'changed root; removed type X12-850.PO1; removed type X12-850.TransactionSet850; added type X12_850.P',
    ('fix', 'thrift'):
        'changed root; removed type FIX.4.4.Message8; added type FIX._4._4.Message8',
    ('flatbuffers', 'thrift'):
        'changed root; changed type example.game.Color; changed type example.game.Monster; changed type examp',
    ('idoc', 'thrift'):
        'changed root; removed type IDOC-ORDERS05.E1EDK01; removed type IDOC-ORDERS05.E1EDK03; removed type I',
    ('iso20022', 'thrift'):
        'changed root; removed type pain.001.001.09.Amt; removed type pain.001.001.09.CdtTrfTxInf; removed ty',
    ('iso8583', 'thrift'):
        'changed root; removed type 0100.DE11; removed type 0100.DE12; removed type 0100.DE13; removed type 0',
    ('kafka-connect', 'thrift'):
        'changed root; changed type com.example.orders.Order',
    ('lwm2m', 'thrift'):
        'removed operation TemperatureService.ResetMinAndMaxMeasuredValues; added operation urn_oma_lwm2m_ext',
    ('matter', 'thrift'):
        'changed operation OnOffService.Off; changed operation OnOffService.OffWithEffect; changed operation ',
    ('nacha', 'thrift'):
        'changed root; removed type NACHA-ACH.AchFile; removed type NACHA-ACH.Batch; removed type NACHA-ACH.B',
    ('ncpdp', 'thrift'):
        'changed root; removed type NCPDP-SCRIPT.Address; removed type NCPDP-SCRIPT.Body; removed type NCPDP-',
    ('protobuf', 'thrift'):
        'changed operation example.catalog.v1.ProductService.CreateProduct; changed operation example.catalog',
    ('protobuf-editions', 'thrift'):
        'changed operation example.orders.v1.OrderService.GetOrder; changed operation example.orders.v1.Order',
    ('sepa', 'thrift'):
        'changed root; removed type pain.001.001.09.Amt; removed type pain.001.001.09.CdtTrfTxInf; removed ty',
    ('wsdl', 'thrift'):
        'removed operation http://example.com/orders.OrderPort.CancelOrder; removed operation http://example.',
    ('wsdl2', 'thrift'):
        'removed operation http://example.com/orders.OrderInterface.cancelOrder; removed operation http://exa',
    # --- wit (12) ---
    ('acp', 'wit'):
        'removed agent research-assistant; added operation apiome:research-assistant.research-assistant.cite-',
    ('agents-manifest', 'wit'):
        'removed operation a2a.https://returns.northwind.example/.well-known/agent-card.json; removed operati',
    ('arazzo', 'wit'):
        'added operation apiome:storefront-checkout.checkout.add-item; added operation apiome:storefront-chec',
    ('graphql', 'wit'):
        'removed operation Query.product; removed operation Query.products; added operation apiome:graph-ql-s',
    ('json-schema', 'wit'):
        'changed root; removed type Product; added type apiome:product.types.product',
    ('jtd', 'wit'):
        'changed root; removed type User; removed type UserAddress; removed type UserStatus; added type apiom',
    ('k8s-crd', 'wit'):
        'changed root; removed service cronwidgets.apps.example.io; added type apps-example-io:cron-widget.ty',
    ('odcs', 'wit'):
        'changed root; added type commerce:orders.types.orders; removed type orders',
    ('owl', 'wit'):
        'changed root; removed type Agent; removed type Customer; removed type Order; removed type OrderLine;',
    ('ros2', 'wit'):
        'changed root; removed type TypicalSensorMessage; removed type TypicalSensorMessage_Constants; added ',
    ('smithy', 'wit'):
        'added operation example-weather:weather-service.weather-service.get-current-conditions; added operat',
    ('typescript-types', 'wit'):
        'changed root; removed type NewOrder; removed type NewOrder_lines_item; removed type Order; removed t',
    # --- xmlrpc (15) ---
    ('a2a', 'xmlrpc'):
        'removed agent Travel Concierge; added operation Build itinerary.Build itinerary; removed operation T',
    ('acp', 'xmlrpc'):
        'removed agent research-assistant; added operation Cite sources.Cite sources; removed operation resea',
    ('agents-manifest', 'xmlrpc'):
        'removed operation a2a.https://returns.northwind.example/.well-known/agent-card.json; removed operati',
    ('arazzo', 'xmlrpc'):
        'added operation addItem.addItem; removed operation checkout#addItem; removed operation checkout#crea',
    ('avro-idl', 'xmlrpc'):
        'added operation cancelOrder.cancelOrder; removed operation com.example.orders.OrderService.cancelOrd',
    ('capnproto', 'xmlrpc'):
        'removed operation Directory.add; removed operation Directory.lookup; added operation add.add; change',
    ('connectrpc', 'xmlrpc'):
        'added operation CompleteTask.CompleteTask; removed operation tasks.v1.TaskService.CompleteTask; remo',
    ('corbaidl', 'xmlrpc'):
        'removed operation Banking.Bank.deposit; removed operation Banking.Bank.getAccount; removed operation',
    ('lwm2m', 'xmlrpc'):
        'added operation ResetMinAndMaxMeasuredValues.ResetMinAndMaxMeasuredValues; removed operation Tempera',
    ('matter', 'xmlrpc'):
        'added operation Off.Off; removed operation OnOffService.Off; removed operation OnOffService.OffWithE',
    ('protobuf', 'xmlrpc'):
        'added operation CreateProduct.CreateProduct; removed operation example.catalog.v1.ProductService.Cre',
    ('protobuf-editions', 'xmlrpc'):
        'added operation GetOrder.GetOrder; removed operation example.orders.v1.OrderService.GetOrder; remove',
    ('thrift', 'xmlrpc'):
        'removed operation com.example.user.UserService.createUser; removed operation com.example.user.UserSe',
    ('wsdl', 'xmlrpc'):
        'added operation CancelOrder.CancelOrder; removed operation http://example.com/orders.OrderPort.Cance',
    ('wsdl2', 'xmlrpc'):
        'added operation cancelOrder.cancelOrder; removed operation http://example.com/orders.OrderInterface.',
    # --- xsd (15) ---
    ('cobolcopybook', 'xsd'):
        'changed root; changed type CUSTOMER-RECORD.CUSTOMER-RECORD',
    ('edifact', 'xsd'):
        'changed root; changed type EDIFACT-INVOIC.DTM; changed type EDIFACT-INVOIC.IMD; changed type EDIFACT',
    ('edix12', 'xsd'):
        'changed root; changed type X12-850.PO1; changed type X12-850.TransactionSet850',
    ('fix', 'xsd'):
        'changed root; changed type FIX.4.4.Message8',
    ('flatbuffers', 'xsd'):
        'changed root; changed type example.game.Color; changed type example.game.Monster; changed type examp',
    ('hl7v2', 'xsd'):
        'changed root; changed type ADT-A01.MSH; changed type ADT-A01.MessageADTA01',
    ('idoc', 'xsd'):
        'changed root; changed type IDOC-ORDERS05.E1EDK01; changed type IDOC-ORDERS05.E1EDK03; changed type I',
    ('iso20022', 'xsd'):
        'changed root; changed type pain.001.001.09.Amt; changed type pain.001.001.09.CdtTrfTxInf; changed ty',
    ('iso8583', 'xsd'):
        'changed root; changed type 0100.DE11; changed type 0100.DE12; changed type 0100.DE13; changed type 0',
    ('kafka-connect', 'xsd'):
        'changed root; changed type com.example.orders.Order',
    ('nacha', 'xsd'):
        'changed root; changed type NACHA-ACH.AchFile; changed type NACHA-ACH.Batch; changed type NACHA-ACH.B',
    ('ncpdp', 'xsd'):
        'changed root; changed type NCPDP-SCRIPT.Address; changed type NCPDP-SCRIPT.Body; changed type NCPDP-',
    ('sepa', 'xsd'):
        'changed root; changed type pain.001.001.09.Amt; changed type pain.001.001.09.CdtTrfTxInf; changed ty',
    ('swift-mt', 'xsd'):
        'changed root; changed type SWIFT-MT103.CodeWord; changed type SWIFT-MT103.Field13C; changed type SWI',
    ('tradacoms', 'xsd'):
        'changed root; changed type TRADACOMS-ORDERS.MessageORDERS; changed type TRADACOMS-ORDERS.OLD',
}
