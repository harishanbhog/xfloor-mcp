import React from 'react';
import { createRoot } from 'react-dom/client';
import { getQuerySnapshot, initializeWidgetBridge, subscribeQuery } from './runtime';
import './styles.css';

function App() {
  const state = React.useSyncExternalStore(subscribeQuery, getQuerySnapshot, getQuerySnapshot);

  if (state.status === 'loading') return <section className="card"><div className="answer">Loading…</div></section>;
  if (state.status === 'error') return <section className="card"><div className="answer">Error: {state.error}</div></section>;
  if (state.status === 'empty') return <section className="card"><div className="answer">No query result yet.</div></section>;

  const data = state.data;
  const answer = data.answer?.trim() || '';
  const related = Array.isArray(data.relatedFloors) ? data.relatedFloors.slice(0, 6) : [];

  return (
    <section className="card">
      <div className="answer">{answer}</div>
      {related.length ? (
        <div className="links">
          {related.map((item, index) => {
            const floorId = (item.floor_id || '').trim();
            const label = (item.label || item.floorName || floorId || '').trim();
            if (!floorId) return null;
            return (
              <a key={index} className="link" href={`https://${floorId}.xfloor.ai`} target="_blank" rel="noreferrer">
                {label.startsWith('@') ? label : `@${label}`}
              </a>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

initializeWidgetBridge();
createRoot(document.getElementById('root')!).render(<App />);
