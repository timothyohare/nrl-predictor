import boto3

ddb = boto3.resource('dynamodb', region_name='ap-southeast-2')
t = ddb.Table('teams')
# scan everything in round 12 and delete rows whose matchId does NOT start with 'round-'
resp = t.scan(
      FilterExpression='#r = :r',
      ExpressionAttributeValues={':r': '12'},
      ExpressionAttributeNames={'#r': 'round'},
)
items = resp['Items']
print(f'Found {len(items)} round-12 rows')
deleted = 0
with t.batch_writer() as batch:
      for i in items:
          # only nuke the slug-based draw rows; team-sheet rows (numeric teamId) stay
          if not i['teamId'].startswith('round-') and '#' in i['teamId']:
              batch.delete_item(Key={'teamId': i['teamId'], 'round': i['round']})
              deleted += 1
print(f'Deleted {deleted} old-format rows')

