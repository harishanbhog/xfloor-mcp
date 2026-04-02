import React from 'react';
import { createRoot } from 'react-dom/client';
import { getSetActiveFloorData } from './runtime';
import './styles.css';

const data = getSetActiveFloorData();
const blocks = Array.isArray(data.blocks) ? data.blocks.slice(0, 6) : [];
const title = data.floor_title || data.floor_ref || 'xFloor';
const floorRef = data.floor_ref ? `@${String(data.floor_ref).replace(/^@/, '')}` : '';
const floorUrl = data.floor_id ? `https://${data.floor_id}.xfloor.ai` : '';

function App() {
  return (
    <section className="card">
      <div className="row">
        {data.floor_logo_url ? <img className="logo" src={data.floor_logo_url} alt="floor logo" /> : null}
        <div>
          <h1 className="title">{title}</h1>
          {floorRef ? <div>{floorRef}</div> : null}
        </div>
      </div>
      {data.floor_description ? <p className="desc">{data.floor_description}</p> : null}
      {blocks.length ? (
        <div className="chips">
          {blocks.map((block, index) => (
            <span key={index} className="chip">{block?.name || block?.block_id || 'Unnamed'}</span>
          ))}
        </div>
      ) : null}
      {floorUrl ? (
        <p style={{ marginTop: 12 }}><a className="link" href={floorUrl} target="_blank" rel="noreferrer">Open floor</a></p>
      ) : null}
    </section>
  );
}

createRoot(document.getElementById('root')!).render(<App />);
