import streamlit as st


_STORAGE_COMPONENT = st.components.v2.component(
    "transaction_browser_storage",
    html="""
<div id="storage-status" role="status" aria-live="polite"></div>
""",
    css="""
#storage-status {
    color: var(--st-text-color);
    font: inherit;
    font-size: 0.8rem;
}
""",
    js="""
export default function (component) {
  const { data, parentElement, setTriggerValue } = component
  const status = parentElement.querySelector("#storage-status")
  const key = data.storageKey

  if (!data.ready) {
    if (status) status.textContent = "Restoring transactions…"
    try {
      const saved = localStorage.getItem(key)
      const payload = saved ? JSON.parse(saved) : null
      setTriggerValue("loaded", {
        transactions: Array.isArray(payload?.transactions) ? payload.transactions : [],
        found: Boolean(saved),
      })
    } catch (error) {
      setTriggerValue("loaded", {
        transactions: [],
        found: false,
        error: "Browser storage could not be read.",
      })
    }
    return
  }

  try {
    const serialized = JSON.stringify({ version: 1, transactions: data.transactions })
    if (localStorage.getItem(key) !== serialized) {
      localStorage.setItem(key, serialized)
    }
    if (status) status.textContent = "Saved in this browser"
  } catch (error) {
    if (status) status.textContent = "Browser storage is full; download a CSV backup."
    setTriggerValue("save_error", "Browser storage is full; download a CSV backup.")
  }
}
""",
)


def browser_transaction_storage(*, storage_key, ready, transactions):
    return _STORAGE_COMPONENT(
        key="browser_transaction_storage",
        data={
            "storageKey": storage_key,
            "ready": ready,
            "transactions": transactions,
        },
        on_loaded_change=lambda: None,
        on_save_error_change=lambda: None,
    )
