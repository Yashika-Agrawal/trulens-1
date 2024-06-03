import streamlit as st
from millify import millify
import math

from trulens_eval.utils.streamlit import init_from_args
from trulens_eval.ux.page_config import set_page_config

# Define your profiles structure
profiles = {
    "profileshub": {
        "client1": ["app1", "app2"],
        "client2": ["app3"]
    },
    "creditpulse": {
        "client3": ["app1", "app2"],
        "client4": ["app3"]
    },
    "filingshub": {
        "client5": ["app1", "app2"],
        "client6": ["app3"]
    },
    "folliosure": {
        "client7": ["app1", "app2"],
        "client8": ["app3"]
    },
}

st.runtime.legacy_caching.clear_cache()

if __name__ == "__main__":
    init_from_args()

def display_dashboard(profile, client, app):
    st.title(f"Dashboard for {app}")
    st.write(f"Profile: {profile}")
    st.write(f"Client: {client}")

    # Example Metrics with Placeholder Values
    latency_mean = 0.123  # Placeholder value
    

    col1, col2, col3 = st.columns(3)
    col1.metric("Average Latency (Seconds)", f"{millify(round(latency_mean, 5), precision=2)}")
   

    # Example Chart: Latency Over Time (Placeholder)
    st.write("### Latency Over Time")
    latency_data = [0.1, 0.15, 0.2, 0.1, 0.3, 0.25]  # Placeholder values
    st.line_chart(latency_data)


    # Example Table: Feedback Scores (Placeholder)
    st.write("### Feedback Scores")
    feedback_scores = {
        "Feedback1": [0.9, 0.85, 0.8, 0.95, 0.88, 0.9],  # Placeholder values
        "Feedback2": [0.7, 0.75, 0.78, 0.8, 0.74, 0.77]  # Placeholder values
    }
    st.table(feedback_scores)

# Main function
def main():
    st.sidebar.title("Navigation")
    st.sidebar.subheader("Profiles")
    profile_selected = st.sidebar.selectbox("Select a profile", list(profiles.keys()))

    if profile_selected:
        st.sidebar.subheader("Clients")
        clients = profiles[profile_selected]
        client_selected = st.sidebar.selectbox("Select a client", list(clients.keys()))

        if client_selected:
            apps = clients[client_selected]
            app_selected = st.sidebar.selectbox("Select an app", apps)

            if app_selected:
                display_dashboard(profile_selected, client_selected, app_selected)
            else:
                st.write("Select an app to view the dashboard.")
        else:
            st.write("Select a client to view the apps.")
    else:
        st.write("Select a profile to view the clients.")

if __name__ == "__main__":
    main()
