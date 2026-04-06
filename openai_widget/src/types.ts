export type SetActiveFloorData = {
  floor_id?: string;
  floor_ref?: string;
  floor_title?: string;
  floor_description?: string;
  floor_logo_url?: string;
  blocks?: Array<{ name?: string; block_id?: string }>;
};

export type QueryRelatedFloor = {
  floor_id?: string;
  floorName?: string;
  label?: string;
};

export type QueryCurrentFloorData = {
  answer?: string;
  relatedFloors?: QueryRelatedFloor[];
};
