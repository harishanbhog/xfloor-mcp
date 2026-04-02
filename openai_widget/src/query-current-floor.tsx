import React from 'react';
import { createRoot } from 'react-dom/client';
import { getQueryCurrentFloorData, getWidgetDataWithRetry, subscribeWidgetData } from './runtime';
import type { QueryCurrentFloorData } from './types';
import './styles.css';

function App() {
  const [data, setData] = React.useState<QueryCurrentFloorData>({});

  React.useEffect(() => {
    let cancelled = false;
    const sync = () => {
      if (!cancelled) setData(getQueryCurrentFloorData() || {});
    };
    const unsubscribe = subscribeWidgetData(sync);
    getWidgetDataWithRetry<QueryCurrentFloorData>().then((next) => {
      if (!cancelled) setData(next || {});
    });
    return () => {
      cancelled = true;
      unsubscribe();
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
