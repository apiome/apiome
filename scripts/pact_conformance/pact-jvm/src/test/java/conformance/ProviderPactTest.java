package conformance;

import au.com.dius.pact.provider.junit5.HttpTestTarget;
import au.com.dius.pact.provider.junit5.PactVerificationContext;
import au.com.dius.pact.provider.junit5.PactVerificationInvocationContextProvider;
import au.com.dius.pact.provider.junitsupport.Provider;
import au.com.dius.pact.provider.junitsupport.State;
import au.com.dius.pact.provider.junitsupport.loader.PactBroker;
import au.com.dius.pact.provider.junitsupport.loader.PactBrokerConsumerVersionSelectors;
import au.com.dius.pact.provider.junitsupport.loader.SelectorBuilder;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.TestTemplate;
import org.junit.jupiter.api.extension.ExtendWith;

/**
 * pact-jvm provider verification: fetches the pacts for {@code ConformanceJvmAPI} from Apiome with
 * consumer-version selectors (pact-jvm's broker client), replays them against the stub provider
 * and publishes the result (PFX-1.8, #6921). The broker URL and token are the
 * {@code pactbroker.url} / {@code pactbroker.auth.token} system properties build.gradle sets.
 */
@Provider("ConformanceJvmAPI")
@PactBroker(enablePendingPacts = "true", providerBranch = "main")
class ProviderPactTest {

    /**
     * The selectors pact-jvm posts to {@code pb:provider-pacts-for-verification}.
     *
     * @return the main branch of every consumer, and whatever is deployed or released.
     */
    @PactBrokerConsumerVersionSelectors
    public static SelectorBuilder consumerVersionSelectors() {
        return new SelectorBuilder().mainBranch().deployedOrReleased();
    }

    /**
     * Point the verifier at the stub provider.
     *
     * @param context pact-jvm's verification context.
     */
    @BeforeEach
    void target(PactVerificationContext context) {
        int port = Integer.parseInt(System.getenv().getOrDefault("PROVIDER_PORT", "8790"));
        context.setTarget(new HttpTestTarget("127.0.0.1", port));
    }

    /**
     * Replay one interaction.
     *
     * @param context pact-jvm's verification context.
     */
    @TestTemplate
    @ExtendWith(PactVerificationInvocationContextProvider.class)
    void verify(PactVerificationContext context) {
        context.verifyInteraction();
    }

    /** The stub always has order 1, so the state needs no set-up. */
    @State("order 1 exists")
    void orderOneExists() {
        // nothing to do
    }
}
