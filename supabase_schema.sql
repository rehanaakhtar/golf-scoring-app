create table if not exists public.game_state (
  id text primary key,
  state jsonb not null,
  updated_at timestamptz not null default timezone('utc', now())
);

insert into public.game_state (id, state)
values (
  'default',
  jsonb_build_object(
    'course', jsonb_build_object(
      'name', 'Islamabad Club',
      'holes', jsonb_build_array()
    ),
    'players', jsonb_build_array(),
    'scores', jsonb_build_object(),
    'updated_at', extract(epoch from now())
  )
)
on conflict (id) do nothing;
