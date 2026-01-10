import { generateOperationId } from '../../lib/utils/path-utils';

describe('generateOperationId', () => {
  it('should generate operation ID without parameters', () => {
    expect(generateOperationId('/api/users', 'GET')).toBe('getApiUsers');
    expect(generateOperationId('/users', 'POST')).toBe('postUsers');
    expect(generateOperationId('/api/v1/products', 'GET')).toBe('getApiV1Products');
  });

  it('should generate operation ID with single parameter using "By"', () => {
    expect(generateOperationId('/user/{userId}', 'GET')).toBe('getUserByUserId');
    expect(generateOperationId('/api/users/{id}', 'GET')).toBe('getApiUsersById');
    expect(generateOperationId('/product/{productId}', 'DELETE')).toBe('deleteProductByProductId');
  });

  it('should generate operation ID with multiple parameters using "By" and "And"', () => {
    expect(generateOperationId('/user/{userId}/{tenantId}', 'GET')).toBe('getUserByUserIdAndTenantId');
    expect(generateOperationId('/api/groups/{groupId}/users/{userId}', 'GET')).toBe('getApiGroupsUsersByGroupIdAndUserId');
    expect(generateOperationId('/tenant/{tenantId}/project/{projectId}/version/{versionId}', 'GET'))
      .toBe('getTenantProjectVersionByTenantIdAndProjectIdAndVersionId');
  });

  it('should handle paths with mixed regular parts and parameters', () => {
    expect(generateOperationId('/api/v1/users/{userId}/profile', 'GET')).toBe('getApiV1UsersProfileByUserId');
    expect(generateOperationId('/organizations/{orgId}/teams/{teamId}/members', 'GET'))
      .toBe('getOrganizationsTeamsMembersByOrgIdAndTeamId');
  });

  it('should handle different HTTP verbs', () => {
    expect(generateOperationId('/user/{userId}', 'POST')).toBe('postUserByUserId');
    expect(generateOperationId('/user/{userId}', 'PUT')).toBe('putUserByUserId');
    expect(generateOperationId('/user/{userId}', 'PATCH')).toBe('patchUserByUserId');
    expect(generateOperationId('/user/{userId}', 'DELETE')).toBe('deleteUserByUserId');
  });

  it('should handle empty or root paths', () => {
    expect(generateOperationId('/', 'GET')).toBe('get');
    expect(generateOperationId('', 'GET')).toBe('get');
  });

  it('should handle paths with special characters', () => {
    expect(generateOperationId('/api-v2/user-profile', 'GET')).toBe('getApiV2UserProfile');
    expect(generateOperationId('/api_v2/user_profile', 'GET')).toBe('getApiV2UserProfile');
  });

  it('should handle parameter names with special characters', () => {
    expect(generateOperationId('/user/{user_id}', 'GET')).toBe('getUserByUserId');
    expect(generateOperationId('/user/{user-id}', 'GET')).toBe('getUserByUserId');
  });

  it('should maintain consistent casing', () => {
    expect(generateOperationId('/API/USERS/{USERID}', 'GET')).toBe('getApiUsersByUserid');
  });
});


