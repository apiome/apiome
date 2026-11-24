package conformance;

import static org.junit.jupiter.api.Assertions.assertEquals;

import au.com.dius.pact.consumer.MockServer;
import au.com.dius.pact.consumer.dsl.PactDslJsonBody;
import au.com.dius.pact.consumer.dsl.PactDslWithProvider;
import au.com.dius.pact.consumer.junit5.PactConsumerTestExt;
import au.com.dius.pact.consumer.junit5.PactTestFor;
import au.com.dius.pact.core.model.PactSpecVersion;
import au.com.dius.pact.core.model.RequestResponsePact;
import au.com.dius.pact.core.model.annotations.Pact;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;

/**
 * pact-jvm consumer test: writes the pact {@code ConformanceJvmWeb → ConformanceJvmAPI} that the
 * Gradle plugin's {@code pactPublish} then sends to Apiome (PFX-1.8, #6921).
 */
@ExtendWith(PactConsumerTestExt.class)
@PactTestFor(providerName = "ConformanceJvmAPI", pactVersion = PactSpecVersion.V3)
class ConsumerPactTest {

    /**
     * The one interaction: GET /orders/1 answers an order with an integer id and a status.
     *
     * @param builder pact-jvm's DSL, bound to the provider.
     * @return the pact.
     */
    @Pact(consumer = "ConformanceJvmWeb")
    RequestResponsePact anOrder(PactDslWithProvider builder) {
        return builder
            .given("order 1 exists")
            .uponReceiving("a request for order 1")
            .path("/orders/1")
            .method("GET")
            .willRespondWith()
            .status(200)
            .headers(Map.of("Content-Type", "application/json"))
            .body(new PactDslJsonBody().integerType("id", 1).stringType("status", "open"))
            .toPact();
    }

    /**
     * Calls the mock provider as the consumer would.
     *
     * @param mockServer pact-jvm's mock of the provider.
     * @throws Exception when the call fails.
     */
    @Test
    void fetchesAnOrder(MockServer mockServer) throws Exception {
        HttpResponse<String> response = HttpClient.newHttpClient()
            .send(HttpRequest.newBuilder(URI.create(mockServer.getUrl() + "/orders/1")).build(),
                HttpResponse.BodyHandlers.ofString());
        assertEquals(200, response.statusCode());
    }
}
