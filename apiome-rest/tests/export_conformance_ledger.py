"""Tracked silent-loss pairs of the export conformance matrix — X1 (#6222). GENERATED.

Each entry is a (source family, target) pair whose export reports no loss while the round trip
shows drift. The gate fails on a silent-loss pair NOT listed here, and on a listed pair that no
longer reproduces (fixed: regenerate to drop it). Drive this list to zero by making the target's
fidelity report name the loss, fixing the emitter, or refusing the pair with a reason.

Regenerate with `UPDATE_EXPORT_CONFORMANCE=1 pytest tests/test_export_conformance_matrix.py`.
"""

from typing import Dict, Tuple

KNOWN_SILENT_LOSS: Dict[Tuple[str, str], str] = {
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
        'added channel com.example.product; added operation 43df6329-226e-4677-ad73-f50348e0bc54; changed roo',
    ('jtd', 'cloudevents'):
        'added channel com.example.user; added operation 11f3b00e-1be6-4186-a851-ae878d78fa8a; changed root; ',
    ('k8s-crd', 'cloudevents'):
        'added channel com.example.cronwidget; added operation 6f3fafe9-4bc3-4b43-a5ee-be48629571f3; changed ',
    ('odcs', 'cloudevents'):
        'added channel com.example.orders; added operation d17c965c-60e7-401d-8343-428bd364e755; changed root',
    ('owl', 'cloudevents'):
        'added channel com.example.commerce.ontology; added operation c6afc2a8-981d-44d4-8a30-b89b0859527e; c',
    ('ros2', 'cloudevents'):
        'added channel com.example.typicalsensormessage; added operation eb6104ea-af13-4eba-b373-fd4d66a05ece',
    ('sparkplug', 'cloudevents'):
        'changed channel spBv1.0/{group_id}/NBIRTH/{edge_node_id}; added operation c7249215-eb39-4824-b0ba-2d',
    ('typescript-types', 'cloudevents'):
        'added channel com.example.orderline; added operation 436737fc-62c4-4107-833c-f068b14e1ef9; changed r',
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
}
