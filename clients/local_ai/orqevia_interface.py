"""Internal Streamlit diagnostics; primary user entry is the trusted PWA."""
import streamlit as st
from shared_client import SharedKnowledgeClient

st.set_page_config(page_title='ORQEVIA internal diagnostics',layout='wide')
st.title('ORQEVIA internal diagnostics')
st.link_button('Open primary ORQEVIA workspace','https://192.168.1.23:8443/pwa/')
st.caption('Internal loopback diagnostic client of the shared service. The primary workspace contains document ingestion, Intelligence and God\'s Eye. No separate index or inference pipeline runs here.')
question=st.text_area('Diagnostic document query',max_chars=4096)
action=st.selectbox('Operation',['health','documents','retrieve','answer'])
if st.button('Run diagnostic'):
    if action in {'retrieve','answer'} and not question.strip():st.warning('Enter a question.')
    else:
        try:
            with st.spinner('Calling the shared local service...'):
                result=SharedKnowledgeClient().call(action,{'question':question} if action in {'retrieve','answer'} else None)
            st.json(result)
        except Exception:st.error('Shared service unavailable or request rejected. Use its primary workspace recovery controls; no independent pipeline was started.')
st.info('The former Singapore point map was demonstration data. Operational maps and attributed stored observations are available in the primary God\'s Eye page.')
