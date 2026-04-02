import React from 'react';
import { createRoot } from 'react-dom/client';
import { getWidgetDataWithRetry } from './runtime';
import type { QueryCurrentFloorData } from './types';
import './styles.css';

function App() {
  const [data, setData] = React.useState<QueryCurrentFloorData>({});

  React.useEffect(() => {
    let cancelled = false;
    getWidgetDataWithRetry<QueryCurrentFloorData>().then((next) => {
      if (!cancelled) setData(next || {});
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const answer = data.answer?.trim() || "Here's what I found.";
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

createRoot(document.getElementById('root')!).render(<App />);
