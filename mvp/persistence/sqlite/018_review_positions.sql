CREATE TABLE review_positions (
 organization_id TEXT NOT NULL, position_key TEXT NOT NULL, name TEXT NOT NULL,
 active INTEGER NOT NULL CHECK(active IN (0,1)), version INTEGER NOT NULL,
 PRIMARY KEY(organization_id,position_key)
);
CREATE TABLE review_position_members (
 organization_id TEXT NOT NULL, position_key TEXT NOT NULL, user_id TEXT NOT NULL REFERENCES auth_users(user_id),
 PRIMARY KEY(organization_id,position_key,user_id),
 FOREIGN KEY(organization_id,position_key) REFERENCES review_positions(organization_id,position_key)
);
